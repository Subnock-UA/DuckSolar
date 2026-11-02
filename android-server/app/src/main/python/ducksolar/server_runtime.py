from __future__ import annotations
from .phone_status import snapshot as phone_snapshot
import copy
import threading
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from .config import ensure_dirs, VERSION
from .core.models import definitions
from .core.device import DeviceMonitor, ParameterReader
from .drivers.registry import create_driver
from .adapters.eybond import EyeBondAdapter
from .storage import Storage
from .finance_service import FinanceService
from .grid_flow import select_grid_flows, decorate_descriptor
from .telemetry_writer import TelemetryWriter
from .memory import BoundedRuntimeStore, MemoryLimits, MemoryHousekeeper
from .logservice import LogService
from .history_reader import HistoryReader
from .services.smartess import SmartESSArchiveService
from .services.tariffs import TariffService
from .api import APIServer

ADAPTERS = {'eybond.lwip': EyeBondAdapter}

class ServerRuntime:
    """Composition root; core polling and DTOs do not depend on an inverter protocol."""
    def __init__(self,cfg):
        self.cfg=cfg
        if not cfg.installation_id:
            from .config import save_config
            cfg.installation_id=uuid4().hex
            save_config(cfg)
        logger_defs,device_defs,self.primary_id=definitions(cfg)
        self.cfg.primary_device_id=self.primary_id
        # Validate every driver and route before opening sockets or changing storage.
        drivers={d.id:create_driver(d.driver,cfg) for d in device_defs}
        if any(d.adapter not in ADAPTERS for d in logger_defs):raise ValueError('Unsupported datalogger adapter')
        adapter_classes={ld.id:ADAPTERS[ld.adapter] for ld in logger_defs}
        for d in device_defs:
            if d.device_code!=drivers[d.id].device_code:raise ValueError('Device code does not match selected profile')
            if d.channel not in adapter_classes[d.logger_id].capabilities['channels']:
                raise ValueError('Unsupported channel for selected datalogger adapter')
        ensure_dirs(cfg);self.logs=LogService(cfg);self.storage=Storage(cfg);self.finance=FinanceService(self.storage,cfg)
        # Android installs start with an empty user database; no Windows sample readings.
        self.adapters={};self.devices={}
        for ld in logger_defs:
            logger_cfg=copy.deepcopy(cfg)
            for k,v in ld.settings.items(): setattr(logger_cfg,k,v)
            targets={}
            for d in device_defs:
                if d.logger_id!=ld.id: continue
                driver=drivers[d.id]
                targets[(d.channel,d.device_code,d.address)]={'device_id':d.id,'requests':driver.read_requests,
                    'valid_response':driver.valid_response,
                    'decode_response':driver.decode_response,
                    'write_validator':__import__('ducksolar.drivers.parameter_library',fromlist=['valid_request']).valid_request,
                    'telemetry_requests':{t.request for t in driver.poll_plan() if t.telemetry}}
            adapter=ADAPTERS[ld.adapter](logger_cfg,log_service=self.logs,targets=targets,logger_id=ld.id)
            adapter.definition=ld
            adapter.cloud_callback=lambda state, ident=ld.id:self._cloud_state(ident,state)
            adapter.event_callback=lambda msg, ident=ld.id:self._logger_event(ident,msg)
            self.adapters[ld.id]=adapter
        for definition in device_defs:
            device_cfg=copy.deepcopy(cfg);device_cfg.history_device_id=definition.id
            adapter=self.adapters[definition.logger_id]
            for k,v in adapter.definition.settings.items(): setattr(device_cfg,k,v)
            driver=drivers[definition.id];driver.cfg=device_cfg
            # Android graphs and balances read persisted history. No API reads
            # live_points, so retaining another ten hours wastes phone memory.
            channel=adapter.create_channel(definition)
            store=BoundedRuntimeStore(MemoryLimits(live_points=0,event_items=256,protocol_preview_items=0))
            writer=TelemetryWriter(device_cfg,self.storage,self.logs)
            monitor=DeviceMonitor(device_cfg,writer,store,self.logs,channel,driver,definition.id)
            self.devices[definition.id]=SimpleNamespace(definition=definition,cfg=device_cfg,driver=driver,channel=channel,
                writer=writer,store=store,housekeeper=MemoryHousekeeper(store),monitor=monitor,
                parameters=ParameterReader(device_cfg,monitor,self.logs),history=HistoryReader(device_cfg))
        primary=self.devices[self.primary_id]
        # Compatibility fields keep existing single-device UI and history working.
        self.gateway=self.adapters[primary.definition.logger_id];self.monitor=primary.monitor
        self.parameters=primary.parameters;self.writer=primary.writer;self.store=primary.store
        self.housekeeper=primary.housekeeper;self.history=primary.history
        self.archive=SmartESSArchiveService(cfg,self.logs)
        self.tariffs=TariffService(cfg,self.storage);self.api=APIServer(self)
        self.session_id=uuid4().hex;self.sequence=0;self._lock=threading.RLock();self._previous={}
        from .network_info import NetworkInfo
        self.network = NetworkInfo(self.logs)
        self.firewall_status = {"state":"NOT_CHECKED"}
        from .events import EventJournal,Transitions
        from .config import app_paths
        self.event_journal=EventJournal(app_paths(cfg)['component_logs']/'Events.jsonl')
        self.transitions=Transitions(self.event_journal)
        from .push_alerts import PushAlerts
        from pathlib import Path
        self.push_alerts=PushAlerts(Path(cfg.root_dir)/'Server/PushAlerts.json',logs=self.logs)
        self.event_stop=threading.Event();self.event_thread=None
        from .parameter_commands import ParameterCommands
        self.commands=ParameterCommands(self)
        self.profile_batches={}
        from .battery_sources import BatterySources
        from .insights import Insights
        from .battery_ledger import BatteryLedger
        self.battery_ledger=BatteryLedger(cfg.root_dir,logs=self.logs)
        self.battery_sources=BatterySources(ledger=self.battery_ledger);self.insights=Insights(self)
        from .night_charge import NightCharge
        self.night_charge=NightCharge(self)
        from .server_forecast import ServerForecast
        self.forecast=ServerForecast(self)
        for ident,dev in self.devices.items():
            self.insights.pv_config(ident)
            dev.monitor.battery_projector=lambda state,ident=ident:self._record_battery(ident,state)
        self.active=False;self._stopped=False;self._stop_lock=threading.Lock()
        from pathlib import Path
        import json
        self.migration_path=Path(cfg.root_dir)/'Data/HistoryMigration/state.json'
        try:self.migration_state=json.loads(self.migration_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.migration_state={}
        self.maintenance_mode=bool(self.migration_state.get('active'))

    def enter_maintenance(self):
        """Keep HTTPS alive, but do not inventory until every writer has stopped."""
        from .prepared_history import write_json
        with self._stop_lock:
            self.maintenance_mode=True;self.active=False
            self.migration_state.update(active=True,stage='stopping',started_at=time.time())
            write_json(self.migration_path,self.migration_state)
            if hasattr(self,'forecast'):self.forecast.cancelled.set()
            if hasattr(self,'maintenance'):self.maintenance.stop_event.set()
            deadline=time.monotonic()+30
            with self.api.jobs.lock:
                futures=[]
                for job in self.api.jobs.jobs.values():
                    job['flag'].set()
                    if job.get('future'):futures.append(job['future'])
            for dev in self.devices.values():dev.monitor.cancel();dev.parameters.stop_event.set()
            if hasattr(self,'forecast'):self.forecast.stop()
            if hasattr(self,'maintenance'):self.maintenance.stop()
            self.archive.stop()
            if self.archive.status().running:raise ValueError('Завантаження ESS ще завершується; повторіть міграцію')
            for adapter in self.adapters.values():adapter.stop()
            for dev in self.devices.values():
                dev.monitor.stop();dev.parameters.stop();dev.writer.stop();dev.housekeeper.stop()
                if dev.writer.thread and dev.writer.thread.is_alive():
                    raise ValueError('Запис ще завершується; повторіть підготовку')
                dev.writer._flush_spool(limit=2**63-1)
                if dev.writer.spool_path.exists() and dev.writer.spool_path.stat().st_size:
                    raise ValueError('Спочатку відновіть помилку запису відкладених вимірювань')
            for future in futures:
                if not future.done():future.result(timeout=max(.01,deadline-time.monotonic()))
            if hasattr(self,'maintenance') and self.maintenance.thread.is_alive():
                raise ValueError('Фонова підготовка ще завершується; повторіть')
            self.migration_state.update(stage='stopped')
            write_json(self.migration_path,self.migration_state)

    def _cloud_state(self,logger_id,state):
        for dev in self.devices.values():
            if dev.definition.logger_id==logger_id: dev.monitor.set_cloud_state(state)

    def _logger_event(self,logger_id,message):
        self.logs.event(message,code='logger.event',logger_id=logger_id)
        for dev in self.devices.values():
            if dev.definition.logger_id==logger_id:
                dev.store.add_event({'time':datetime.now().isoformat(sep=' ',timespec='seconds'),
                    'code':'logger.event','logger_id':logger_id,'device_id':dev.definition.id,'message':message})

    def start(self):
        self.logs.event('Server started: Beta '+VERSION,code='server.started')
        try:
            from .windows_firewall import ensure_firewall
            self.firewall_status = ensure_firewall(self.logs)
            self.api.start()
            for adapter in self.adapters.values(): adapter.start()
            self.active=True
            self.network.start()
            self.battery_sources.start()
            self.forecast.start_scheduler()
            for dev in self.devices.values():
                dev.writer.start();dev.housekeeper.start();dev.monitor.start()
                if self.cfg.equipment_mode!='relay_only':dev.parameters.start()
            def observe():
                next_supervision=0
                while not self.event_stop.wait(1):
                    try:
                        for ident,dev in self.devices.items():
                            state=self.device_snapshot(dev)
                            self.insights.observe(ident,state)
                            self.transitions.observe(ident,state)
                            self.push_alerts.observe(ident,state)
                            self.night_charge.tick(ident)
                            online=state['statuses']['Inverter']
                            if self._previous.get(ident)!=online:
                                self._previous[ident]=online
                                self.logs.event('Inverter '+('online' if online else 'offline'),code='device.online' if online else 'device.offline',device_id=ident)
                        write_error=any(bool(getattr(dev.writer,'_last_disk_error','')) for dev in self.devices.values())
                        # Phone probe separately supplies actual charging/free-space values.
                        self.push_alerts.storage_failure(write_error)
                        if self.active and not self._stopped and time.monotonic()>=next_supervision:
                            next_supervision=time.monotonic()+30
                            for ident,dev in self.devices.items():
                                for role,worker in (('monitor',dev.monitor),('writer',dev.writer),('parameters',dev.parameters)):
                                    if worker.thread is not None and not worker.thread.is_alive() and not self.event_stop.is_set():
                                        self.logs.event('Restarting stopped worker',code='server.worker_restarted',device_id=ident,worker=role)
                                        worker.start()
                    except Exception:self.logs.exception('Event observer failed',code='events.failed')
            self.event_thread=threading.Thread(target=observe,name='ServerEvents',daemon=True);self.event_thread.start()
        except Exception:
            self.stop();raise

    def device(self,device_id=None):
        key=device_id or self.primary_id
        try: return self.devices[key]
        except KeyError: raise ValueError('Unknown device ID: '+str(key))

    def _record_battery(self,ident,state):
        from .battery_projection import apply
        params=self.device(ident).parameters.snapshot()
        live=dict(state,stale=False,parameters=params)
        result=self.battery_sources.view(ident,live,self.insights.config(ident))
        apply(state,result)

    def device_snapshot(self,dev):
        state=dev.monitor.snapshot();adapter=self.adapters[dev.definition.logger_id]
        received=state.pop('received_monotonic',None)
        age=max(0,time.monotonic()-received) if received is not None else None
        mode_received=state.pop('mode_received_monotonic',None)
        mode_connection=state.pop('mode_connection_id',None)
        mode_age=max(0,time.monotonic()-mode_received) if mode_received is not None else None
        state.update(mode_age_s=mode_age,mode_stale=self.maintenance_mode or not adapter.connected or mode_connection!=adapter.connection_id or mode_age is None or mode_age>30)
        from .telemetry_health import health
        quality=health(adapter.connected,state.get('measurement_connection_id')==adapter.connection_id,age,max(15,dev.cfg.poll_interval_s*3+dev.cfg.socket_timeout_s),reply_age=getattr(dev.channel,'inverter_reply_age',None))
        online=quality['fresh']
        state.update(telemetry_status=quality['status'],inverter_connected=quality['connected'])
        p=dev.parameters.snapshot();raw=p['raw']
        descriptor = dev.driver.descriptor(dev.definition, raw)
        from .event_codes import decode_warnings
        decoded_warnings=decode_warnings(state.get('warnings',''),descriptor.get('profile_confirmed',False))
        state.update(warning_events=decoded_warnings['events'],warnings_display=decoded_warnings['display'],warnings_valid=decoded_warnings['valid'])
        from .pv_profiles import profile
        descriptor['pv_profile']=profile(self.cfg,dev.definition.id,dev.driver.identity(raw))
        descriptor['metric_definitions'] = [s.to_dict() for s in dev.driver.specs if s.command != 'QPIRI']
        normalized = select_grid_flows(state.get('normalized') or dev.driver.normalized(state.get('data',{})), datetime.now())
        descriptor = decorate_descriptor(descriptor, normalized)
        descriptor['metric_definitions'].append(dict(canonical_id='output.power_factor',ui_name='Коефіцієнт потужності PF',unit=''))
        from .monitor_metrics import add_metrics
        normalized["metrics"]=dev.monitor.display_retention.apply(normalized.get("metrics",{}),adapter.connection_id,online and not self.maintenance_mode)
        state.update(statuses={'LWIP':adapter.connected,'Inverter':quality['connected'],'Cloud':adapter._cloud_state=='CONNECTED','API':self.active or self.maintenance_mode},
            stale=self.maintenance_mode or not online,age_s=age,connection=adapter.snapshot_status().state,
            descriptor=descriptor,normalized=normalized,
            parameters={'status':p['status'],'status_code':p['status_code'],'updated':p['updated'],'error':p['error'],
                'error_code':p['error_code'],'stale':p['stale'],'identity':dev.driver.identity(raw),
                'rows':dev.driver.parameter_catalog(raw),'raw':raw,'raw_text':'\n\n'.join(k+'\n'+str(v) for k,v in raw.items())})
        for row in state['parameters']['rows']:
            try:self.night_charge.guard(dev.definition.id,row.get('canonical_id'))
            except ValueError as error:row.update(writable=False,write_reason=str(error))
        from .pv_accounting import power,VERSION as PV_BASIS
        from .pv_accounting import project
        projection=project(dict(state.get('data',{}),timestamp=state.get('updated') or datetime.now(),normalized=state['normalized']),dev.cfg)
        state['normalized']=projection.get('normalized',state['normalized'])
        from .display_metrics import pv
        corrected=projection.get('pv_corrected_w')
        pv(state['normalized'].setdefault('metrics',{}),corrected,not state['stale'])
        state['pv_accounted_w']=state['normalized']['metrics'].get('pv.total_power',{}).get('value')
        state['normalized'],state['descriptor']=add_metrics(state['normalized'],state['descriptor'],dev.cfg)
        from .battery_projection import apply as battery_apply,descriptor as battery_descriptor
        battery_apply(state,self.battery_sources.view(dev.definition.id,state,self.insights.config(dev.definition.id)))
        battery_descriptor(state['descriptor'])
        with dev.store._lock: state['events']=list(dev.store.events)[-100:]
        return state

    def descriptors(self):
        return [self.device_snapshot(dev)['descriptor'] for dev in self.devices.values()]

    def dictionary(self,device_id=None):
        dev=self.device(device_id)
        return {'device_id':dev.definition.id,'profile':dev.driver.id,'parameters':[s.to_dict() for s in dev.driver.specs],
                'own_write_commands_enabled':any(r['writable'] for r in dev.driver.parameter_catalog(dev.parameters.snapshot()['raw']))}

    def snapshot(self):
        with self._lock:
            devices={key:self.device_snapshot(dev) for key,dev in self.devices.items()}
            state=copy.deepcopy(devices[self.primary_id]);self.sequence+=1
            state.update(server_time=datetime.now().isoformat(timespec='microseconds'),server_utc=datetime.now(timezone.utc).isoformat(timespec='microseconds'),api_version=3,state_schema=2,server_version=VERSION,session_id=self.session_id,
                sequence=self.sequence,primary_device_id=self.primary_id,devices=devices,
                maintenance=dict(active=self.maintenance_mode,stage=self.migration_state.get('stage','')),
                loggers={key:{'id':key,'name':a.definition.name,'adapter':a.definition.adapter,
                    'connection':a.snapshot_status().__dict__,'cloud':a._cloud_state,'capabilities':a.capabilities}
                    for key,a in self.adapters.items()},
                network=self.network.snapshot(), firewall=dict(self.firewall_status),
                server_phone=phone_snapshot(),
                locale={'current':'uk-UA','date_format':'dd.mm.yyyy','selector_available':False})
            return state

    def stop(self):
        with self._stop_lock:
            if self._stopped:return
            self._stopped=True;self.logs.event('Server stopping',code='server.stopping');self.active=False
            self.event_stop.set()
            if hasattr(self,'forecast'):self.forecast.stop()
            if hasattr(self,'maintenance'):self.maintenance.stop()
            self.api.jobs.stop()
            self.api.month_accounting.stop_event.set()
            if self.event_thread:self.event_thread.join(timeout=3)
            self.battery_sources.stop()
            self.battery_ledger.save()
            for dev in self.devices.values(): dev.monitor.cancel();dev.parameters.stop_event.set()
            operations=[('network',self.network.stop),('archive',self.archive.stop)]
            operations += [(key,adapter.stop) for key,adapter in self.adapters.items()]
            for key,dev in self.devices.items():
                operations.extend([(key+' monitor',dev.monitor.stop),(key+' parameters',dev.parameters.stop),
                    (key+' writer',dev.writer.stop),(key+' memory',dev.housekeeper.stop)])
            operations.append(('API',self.api.stop))
            for name,stop in operations:
                try:stop()
                except Exception as exc:self.logs.event('Shutdown '+name+' error: '+str(exc),code='server.stop_error')
            self.logs.event('Server stopped',code='server.stopped');self.logs.close()
