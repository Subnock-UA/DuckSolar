"""Android host boundary; no desktop imports or shared Windows data."""
import os,json,threading,ipaddress,ssl,sqlite3,sys,time,gc,traceback
from pathlib import Path
_lock=threading.RLock()
_runtime=None
_last_stopped=None
_root=None
_mode='offline'
_history_archive=None
_charging=False
_sync_cancel=threading.Event()
_sync_io=threading.RLock()
_sync_cleanup=None
_sync_in_progress=False

def _schedule_sync_cleanup(runtime):
    global _sync_cleanup
    from ducksolar.history_sync import base,cleanup_after_commit
    if _sync_cleanup and _sync_cleanup.is_alive():return
    if not (base(runtime)/'cleanup-pending.json').exists():return
    def cleanup():
        try:cleanup_after_commit(runtime)
        except Exception as error:runtime.logs.event('History cleanup deferred',code='history.sync.cleanup_deferred',error=str(error))
    _sync_cleanup=threading.Thread(target=cleanup,name='HistorySyncCleanup',daemon=True);_sync_cleanup.start()

def sync_pending_id():
    if _runtime is None:return ''
    from ducksolar.history_sync import base,load
    value=load(base(_runtime)/'local-plan.json',{})
    return value.get('request',{}).get('id','')

def _sync_restart_collection():
    global _runtime
    cfg=_runtime.cfg;offline=_mode=='offline'
    _runtime.migration_state.update(active=False,stage='ready')
    from ducksolar.sync_store import atomic
    atomic(_runtime.migration_path,_runtime.migration_state)
    stop();start(cfg.lwip_ip,cfg.dtu_pn,offline,cfg.equipment_mode)

def sync_request_stop():
    # No global runtime lock: cancellation must reach inventory/transfer promptly.
    _sync_cancel.set()
    return True

def sync_begin():
    global _sync_cleanup,_sync_in_progress
    if _sync_cleanup and _sync_cleanup.is_alive():_sync_cleanup.join()
    _sync_cancel.clear();_sync_in_progress=True
    from ducksolar import history_sync as sync
    from ducksolar.sync_store import Store,release_store
    from ducksolar.compact_history import schema_path
    from datetime import date
    with _lock:
        if _runtime is None:raise ValueError('Спочатку запустіть сервер')
        journal=sync.load(sync.base(_runtime)/'activation.json',{})
        if journal.get('stage')=='complete':
            (sync.base(_runtime)/'local-plan.json').unlink(missing_ok=True);(sync.base(_runtime)/'activation.json').unlink(missing_ok=True)
            _sync_restart_collection()
            _sync_in_progress=False;_schedule_sync_cleanup(_runtime)
            return json.dumps(dict(completed=True,message='Історія застосована; збір відновлено'),ensure_ascii=False)
        if journal.get('stage')=='applying':
            _runtime.enter_maintenance();_runtime._sync_transfer_queue=None
            manifest=sync.load(journal.get('manifest',''),{})
            pending=sync.load(sync.base(_runtime)/'local-plan.json',{})
            if not pending.get('request'):raise ValueError('Відсутній збережений план відновлення активації')
            if manifest and sync.hashed(manifest)==journal.get('generation') and not sync.transfer_plan(_runtime,journal['manifest'])['items']:
                return sync_activate(journal['manifest'],recover=True)
            return json.dumps(pending['request'],ensure_ascii=False)
        pending=sync.load(sync.base(_runtime)/'local-plan.json',{})
        if pending.get('request') and pending.get('inventory_revision')==2 and pending['request']['model']==dict(_runtime.history.model_signature()):
            if _runtime.maintenance_mode:_sync_restart_collection()
            return json.dumps(pending['request'],ensure_ascii=False)
        # Only capture appendable inputs while collection is paused. All large
        # inventory/CAS/cache work happens after collection has restarted.
        frozen={};runtime=_runtime;sync.progress(runtime,'stopping_collection')
        try:
            runtime.enter_maintenance()
            store=Store(sync.base(runtime)/'store')
            for path in runtime.history.find_day_files(date.today())[0]:
                path=path.resolve()
                if path.parent not in (runtime.history.paths['inverter_logs'].resolve(),(Path(runtime.cfg.root_dir)/'Data/CompactHistory'/runtime.primary_id/'Local').resolve()):continue
                frozen[str(path)]=dict(csv=store.snapshot(path,immutable=True,cancelled=_sync_cancel.is_set),schema=store.snapshot(schema_path(path),immutable=True,cancelled=_sync_cancel.is_set) if schema_path(path).exists() else None)
            store.save()
        finally:
            if _runtime and sync.load(sync.base(_runtime)/'activation.json',{}).get('stage')!='applying':_sync_restart_collection()
        runtime=_runtime
    sync.progress(runtime,'inventory')
    try:
        result=sync.begin(runtime,frozen=frozen,cancelled=_sync_cancel.is_set)
        sync.progress(runtime,'transferring')
        return json.dumps(result,ensure_ascii=False)
    except Exception:
        sync.progress(runtime,'paused');raise


def sync_block_source(sha):
    from ducksolar.history_sync import block_source
    return block_source(_runtime,sha)

def sync_has_block(sha,length):
    from ducksolar.sync_store import Store
    from ducksolar.sync_store import session_store
    with session_store(Path(_runtime.cfg.root_dir)/'Data/HistorySync/store') as store:return store.has(dict(sha256=sha,bytes=int(length)))

def sync_accept_block(sha,path):
    from ducksolar.sync_store import Store
    from ducksolar.sync_store import session_store
    with session_store(Path(_runtime.cfg.root_dir)/'Data/HistorySync/store') as store:store.put(sha,Path(path).read_bytes())
    return True

def sync_materialize_manifest(descriptor):
    from ducksolar.sync_store import Store
    folder=Path(_runtime.cfg.root_dir)/'Data/HistorySync';store=Store(folder/'store');desc=json.loads(descriptor)
    target=folder/'downloads'/(desc['sha256']+'.json');store.materialize(desc,target);store.save();return str(target)

def sync_missing(path):
    from ducksolar.history_sync import missing
    return json.dumps(missing(_runtime,path),ensure_ascii=False)

def sync_transfer_plan(path):
    from ducksolar.history_sync import transfer_plan
    with _sync_io:return json.dumps(transfer_plan(_runtime,path),ensure_ascii=False)

def sync_activate(path,recover=False):
    global _sync_cleanup,_sync_in_progress
    from ducksolar.history_sync import activate,base,load,cleanup_after_commit,progress,prepare_activation,abandon_staging
    from ducksolar.sync_store import release_store
    with _lock:
        if _runtime is None:raise ValueError('Спочатку запустіть сервер')
        runtime=_runtime;release_store(base(runtime)/'store')
        # Heavy immutable validation does not need to suspend live collection.
        prepare_activation(runtime,path)
        progress(runtime,'stopping_for_commit')
        try:
            runtime.enter_maintenance()
            result=activate(runtime,path)
        except Exception as error:
            runtime.logs.event('History activation failed',code='history.sync.failed',error=str(error),exception_class=type(error).__name__,errno=getattr(error,'errno',None),filename=str(getattr(error,'filename',None)),traceback=traceback.format_exc())
            if abandon_staging(runtime):_sync_restart_collection()
            raise
        _sync_restart_collection()
        runtime=_runtime
        runtime.logs.event('History synchronization activated',code='history.sync.activated',generation=result['generation'],stats=result['stats'])
        _sync_in_progress=False;_schedule_sync_cleanup(runtime)
        if recover:result.update(completed=True,message='Перервану активацію завершено; збір відновлено')
        return json.dumps(result,ensure_ascii=False)

def sync_cancel_local():
    global _sync_in_progress
    _sync_cancel.set()
    with _lock:
        from ducksolar.history_sync import base,load,progress,abandon_staging
        from ducksolar.sync_store import release_store
        if _runtime is None:
            from ducksolar.config import load_config
            cfg=_last_stopped.cfg if _last_stopped else load_config()
            start(cfg.lwip_ip,cfg.dtu_pn,_mode=='offline',cfg.equipment_mode)
            if _runtime.maintenance_mode and not abandon_staging(_runtime):raise ValueError('Спочатку завершіть відновлення активації історії')
        folder=base(_runtime);journal=load(folder/'activation.json',{})
        if journal.get('stage')=='complete':(folder/'activation.json').unlink(missing_ok=True)
        if journal.get('stage')=='applying' and not abandon_staging(_runtime):raise ValueError('Встановлення історії вже почалось; продовжіть синхронізацію для безпечного відновлення')
        release_store(folder/'store')
        plan=folder/'local-plan.json'
        if plan.exists():plan.replace(folder/('paused-'+str(time.time_ns())+'.json'))
        if _runtime.maintenance_mode:_sync_restart_collection()
        _sync_in_progress=False;progress(_runtime,'paused')
        return 'Синхронізацію зупинено. Збір даних працює; отримані блоки та кеші збережені.'

def sync_progress():
    if _runtime is None:return '{}'
    from ducksolar.history_sync import base,load
    return json.dumps(load(base(_runtime)/'progress.json',{}),ensure_ascii=False)


def migration_current_id():
    with _lock:
        if _runtime is None or not _runtime.maintenance_mode:return ''
        path=Path(_runtime.cfg.root_dir)/'Data/HistoryMigration/plan.json'
        return json.loads(path.read_text(encoding='utf-8'))['id'] if path.exists() else ''

def migration_begin():
    with _lock:
        if _runtime is None:raise ValueError('Спочатку запустіть сервер')
        plan_path=Path(_runtime.cfg.root_dir)/'Data/HistoryMigration/plan.json'
        if _runtime.migration_state.get('stage')=='ready' and not _runtime.maintenance_mode:
            from ducksolar.compact_history import schema_path
            reader=_runtime.history
            raw=any(not schema_path(path).exists() for day in reader.available_dates(refresh=True) for group in reader.find_day_files(day) for path in group)
            if not raw:
                from ducksolar.history_migration import active_folder
                from ducksolar.projection_contract import CONTRACT as INDEX_CONTRACT
                active=active_folder(_runtime.cfg.root_dir,_runtime.primary_id)
                manifest=json.loads((active.parent/'manifest.json').read_text(encoding='utf-8')) if active else {}
                if manifest.get('projection_contract')==INDEX_CONTRACT:
                    return json.dumps(dict(completed=True,message='Історія та індекси вже узгоджені'),ensure_ascii=False)
                if not plan_path.exists():raise ValueError('Для оновлення індексів потрібен збережений план міграції')
                _runtime.migration_state['repair_only']=True
            if raw:_runtime.migration_state.pop('repair_only',None)
            if raw and plan_path.exists():
                old=json.loads(plan_path.read_text(encoding='utf-8'))
                plan_path.replace(plan_path.with_name('plan-'+old['id']+'.complete.json'))
        if _history_archive:_history_archive.stop()
        _runtime.enter_maintenance()
        if _history_archive and _history_archive.status().running:raise ValueError('Завантаження ESS ще завершується; повторіть міграцію')
        from ducksolar.history_migration import inventory
        return json.dumps(inventory(_runtime),ensure_ascii=False)

def migration_activate(path,sha):
    with _lock:
        if _runtime is None or not _runtime.maintenance_mode:raise ValueError('Сервер має бути в режимі обслуговування')
        from ducksolar.history_migration import activate
        result=activate(_runtime,path,sha)
        cfg=_runtime.cfg;offline=_mode=='offline'
        stop();start(cfg.lwip_ip,cfg.dtu_pn,offline,cfg.equipment_mode)
        if _runtime:_runtime.logs.event('Collection resumed after migration',code='history.migration.resumed',generation=result.get('generation'))
        return json.dumps(result,ensure_ascii=False)

def migration_resume_collection():
    with _lock:
        if _runtime is None:raise ValueError('Спочатку запустіть сервер')
        rt=_runtime
        if not rt.maintenance_mode:return 'Збір уже працює'
        stage=rt.migration_state.get('stage','')
        if stage not in ('stopping','stopped'):
            raise ValueError('Активація історії вже почалась; спочатку завершіть міграцію')
        cfg=rt.cfg;offline=_mode=='offline'
        stop()
        plan=Path(cfg.root_dir)/'Data/HistoryMigration/plan.json'
        if plan.exists():
            plan.replace(plan.with_name('plan-paused-'+str(time.time_ns())+'.json'))
        from ducksolar.prepared_history import write_json
        rt.migration_state.update(active=False,stage='paused')
        write_json(rt.migration_path,rt.migration_state)
        start(cfg.lwip_ip,cfg.dtu_pn,offline,cfg.equipment_mode)
        return 'Збір відновлено. Архіви збережено. Наступна оптимізація створить актуальний план.'

def ess_history_status():
    from dataclasses import asdict
    return json.dumps(asdict(_history_archive.status()) if _history_archive else {'running':False,'message':'Історію ESS ще не завантажували'},ensure_ascii=False)

def ess_history_start(username,password,pn,start_day,end_day):
    global _history_archive
    if _runtime and _runtime.maintenance_mode:raise ValueError('Міграція історії триває; завантаження ESS призупинено')
    from datetime import date
    from ducksolar.config import load_config
    from ducksolar.services.smartess import SmartESSArchiveService
    start,end=date.fromisoformat(start_day),date.fromisoformat(end_day)
    if end>=date.today() or not 0<=(end-start).days<31:raise ValueError('Оберіть до 31 завершеного дня історії')
    cfg=load_config()
    if pn.strip()!=cfg.dtu_pn or not pn.strip():raise ValueError('PN має відповідати логеру цього сервера')
    if not username.strip() or not password:raise ValueError('Вкажіть облікові дані ESS')
    with _lock:
        if _history_archive is None:_history_archive=SmartESSArchiveService(cfg)
        # Credentials are used in memory for this task only, not DPAPI or client storage.
        _history_archive.start_download({'username':username.strip(),'password':password,'pn':pn.strip()},start,end)
    return ess_history_status()

def ess_history_stop():
    if _history_archive:_history_archive.stop()
    return ess_history_status()

def initialize(root,bundle=''):
    global _root
    _root=Path(root)/'DuckSolar';_root.mkdir(parents=True,exist_ok=True)
    os.environ['DUCK_SOLAR_ROOT']=str(_root)
    os.environ['DUCK_SOLAR_ROLE']='Server'
    from ducksolar.meter_bootstrap import import_snapshot
    import_snapshot(_root)
    # The archive was a one-time a1.4.7 migration. Do not repeat or overwrite it.
    if bundle:
        from ducksolar.archive_bootstrap import import_bundle
        result=import_bundle(_root,Path(bundle))
        (_root/'ARCHIVE_IMPORT.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    return status()

def start(ip='',pn='',offline=True,equipment_mode='normal'):
    global _runtime,_mode
    with _lock:
        if _runtime is not None:return status()
        if _root is None:raise RuntimeError('Android host not initialized')
        from ducksolar.config import load_config,save_config
        from ducksolar.server_runtime import ServerRuntime
        if equipment_mode not in ('normal','local_only','relay_only'):
            raise ValueError('Unknown equipment mode')
        cfg=load_config();cfg.equipment_mode=equipment_mode
        cfg.cloud_proxy_enabled=not offline and equipment_mode!='local_only'
        # Monitoring owns the logger destination; offline mode never redirects it.
        cfg.auto_redirect_enabled=not offline
        cfg.native_cloud_route=not offline
        # Give the logger time to reconnect before resending the destination.
        cfg.redirect_retry_s=60.0
        cfg.lwip_ip=ip or ('127.0.0.1' if offline else '');cfg.dtu_pn=pn or ''
        if cfg.cloud_host=='vip1.eybond.com' and cfg.cloud_port==502:
            cfg.cloud_host='vip1.eybond.com'
        cfg.api_host='0.0.0.0';cfg.api_port=28766
        cfg.log_max_bytes=1024*1024;cfg.log_backups=3
        if not offline:
            addr=ipaddress.ip_address(ip)
            if not addr.is_private or addr.is_loopback or not pn.strip():
                raise ValueError('Р’РєР°Р¶С–С‚СЊ Р»РѕРєР°Р»СЊРЅСѓ IP-Р°РґСЂРµСЃСѓ EyBond С– Р№РѕРіРѕ PN')
        save_config(cfg)
        rt=ServerRuntime(cfg)
        try:
            if rt.maintenance_mode:
                rt.api.start()
            elif offline:
                # Real authenticated HTTPS API, no gateway redirect or inverter I/O.
                rt.api.start();rt.active=True
            else:rt.start()
            _runtime=rt;_mode='offline' if offline else 'eybond'
            from ducksolar.history_maintenance import HistoryMaintenance
            if not rt.maintenance_mode:
                rt.maintenance=HistoryMaintenance(rt);rt.maintenance.power(_charging)
        except BaseException:
            rt.stop();raise
        if not _sync_in_progress:_schedule_sync_cleanup(rt)
        return status()

def stop():
    global _runtime,_last_stopped
    with _lock:
        rt,_runtime=_runtime,None
        _last_stopped=rt
        if rt:rt.stop()
        gc.collect()
        return status()

def status():
    with _lock:
        out={'running':_runtime is not None,'display_version':'b1.0.24','api_version':3,
             'mode':_mode,'port':28766,'python':sys.version.split()[0],
             'month_balance_available':True,'push_available':False}
        if _runtime:
            out['maintenance']=dict(active=_runtime.maintenance_mode,stage=_runtime.migration_state.get('stage',''))
            out['fingerprint']=_runtime.api.fingerprint
            out['lan_ips']=_runtime.network.snapshot().get('lan_ips',[])
            primary=_runtime.device_snapshot(_runtime.device())
            out['connection']=primary['connection']
            out['stale']=primary['stale']
            out['updated']=primary.get('updated','')
            out['last_error']=primary.get('last_error','')
            out['auto_redirect_enabled']=_runtime.cfg.auto_redirect_enabled
            out['ess_polling']=_runtime.gateway.shadow.snapshot()
            out['cloud_endpoint']=str(_runtime.gateway.cfg.cloud_host)+':'+str(_runtime.gateway.cfg.cloud_port)
            out['sample_source']=primary.get('sample_source','Local')
            out['ess_connection']=primary.get('cloud','DISCONNECTED')
            out['ess_target']=f'{_runtime.cfg.cloud_host}:{_runtime.cfg.cloud_port}'
            out['logger_ip']=_runtime.gateway.cfg.lwip_ip
            route=getattr(_runtime.gateway,'native_route',None)
            out['logger_route']=route.snapshot() if route else {}
            out['equipment_mode']=_runtime.cfg.equipment_mode
            out['channel_health']=_runtime.gateway.health_snapshot()
            from ducksolar.concurrency import snapshot as parallel_snapshot
            out['parallel_execution']=parallel_snapshot()
            from ducksolar.cpu_energy import status as cpu_status
            out['cpu_execution']=cpu_status()
        elif _last_stopped:
            route=getattr(_last_stopped.gateway,'native_route',None)
            out['logger_route']=route.snapshot() if route else {}
            out['route_restored']=not route or route.state=='RESTORED'
            out['route_error']=route.last_error if route and route.state!='RESTORED' else ''
        return json.dumps(out,ensure_ascii=False)

def pairing_code():
    with _lock:
        if not _runtime:raise ValueError('РЎРїРѕС‡Р°С‚РєСѓ Р·Р°РїСѓСЃС‚С–С‚СЊ СЃРµСЂРІРµСЂ')
        return _runtime.api.pairing.generate()

def import_history(path,metadata):
    with _lock:
        if _runtime and _runtime.maintenance_mode:raise ValueError('Міграція триває; імпорт історії призупинено')
        from ducksolar.synchronized_history import import_file
        result=import_file(_root,path,metadata)
        if _runtime:
            # Reader instances refresh file discovery for the next request.
            for device in _runtime.devices.values():device.history._dates_cache_at=0
    return json.dumps(result,ensure_ascii=False)

def history_import_status(metadata):
    from ducksolar.synchronized_history import import_status
    return import_status(_root,metadata)

def history_inventory():
    from ducksolar.config import load_config
    from ducksolar.history_reader import HistoryReader
    reader=HistoryReader(load_config());days=reader.available_dates(refresh=True)
    return json.dumps({'days':len(days),'first':days[0].isoformat() if days else None,'last':days[-1].isoformat() if days else None,
                      'local_files':sum(len(v[0]) for v in reader._file_index.values()),'ess_files':sum(len(v[1]) for v in reader._file_index.values()),
                      'archive':reader._archive_diagnostics},ensure_ascii=False)

def recover_ess_route(metadata):
    import re
    from ducksolar.config import load_config
    row=json.loads(metadata);cfg=load_config();host=row.get('original_endpoint','');port=int(row.get('original_port',0))
    if row.get('pn')!=cfg.dtu_pn or not cfg.dtu_pn:raise ValueError('Маршрут належить іншому PN')
    if not re.fullmatch('[A-Za-z0-9.-]{1,253}',host) or '.' not in host or not 1<=port<=65535:raise ValueError('Некоректний endpoint ESS')
    try:
        if not ipaddress.ip_address(host).is_global:raise ValueError('Локальна адреса не є штатним ESS endpoint')
    except ValueError as exc:
        if re.fullmatch(r'[0-9.]+',host):raise exc
    with _lock:
        if _runtime is not None:raise ValueError('Спочатку зупиніть сервер, потім відновіть збережений endpoint')
        path=_root/'Server/NativeRoutes/logger-1.json';path.parent.mkdir(parents=True,exist_ok=True)
        old=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if old.get('original_endpoint') and (old['original_endpoint'],int(old.get('original_port',502)))!=(host,port):raise ValueError('Чинний збережений endpoint відрізняється; його не перезаписано')
        if old.get('pn') and old['pn']!=cfg.dtu_pn:raise ValueError('Наявний запис належить іншому PN')
        record=dict(old,pn=cfg.dtu_pn,original_endpoint=host,original_port=port,active=False,stage='recovered_from_pc',recovery_proof=row)
        temporary=path.with_suffix('.tmp')
        with temporary.open('w',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False);f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    return json.dumps({'state':'saved','endpoint':host,'port':port,'hardware_changed':False},ensure_ascii=False)

def resource_state(available,threshold,total,low=False):
    from ducksolar.resource_manager import update,pressure
    update(available,threshold,total,low)
    rt=_runtime
    if rt:
        rt.logs.event('Equipment channel heartbeat',code='network.channels',**rt.gateway.health_snapshot())
    if low and rt:
        # Drop ownership of reusable job caches; active jobs retain their local
        # context until they finish, without clearing data under their iterator.
        with rt.api.job_context_lock:
            rt.api.job_contexts.clear()
        if rt.api.history_lock.acquire(blocking=False):
            try:pressure(rt,rt.api.history_views)
            finally:rt.api.history_lock.release()

def battery_state(level,scale=100):
    runtime=_runtime
    if runtime and type(level) is int and type(scale) is int and 0<=level<=scale and scale>0:
        runtime.push_alerts.battery(100*level/scale)


def power_state(charging):
    global _charging
    _charging=bool(charging)
    rt=_runtime
    if rt and hasattr(rt,'maintenance'):rt.maintenance.power(_charging)

def graph_cache_status():
    rt=_runtime
    owner=rt if rt is not None else _last_stopped
    job=getattr(getattr(owner,'maintenance',None),'graph_cache',None)
    if job is not None:state=job.status()
    else:
        try:state=json.loads((_root/'Data/PreparedHistory/graph-cache-job.json').read_text('utf-8'))
        except (OSError,ValueError):state={'state':'idle'}
    state['server_running']=rt is not None and job is not None
    return json.dumps(state,ensure_ascii=False)


def graph_cache_start():
    with _lock:
        if _runtime is None or not hasattr(_runtime,'maintenance'):raise ValueError('Спочатку запустіть сервер')
        result=_runtime.maintenance.graph_cache.request(manual=True);result['server_running']=True
        return json.dumps(result,ensure_ascii=False)


def graph_cache_cancel():
    with _lock:
        if _runtime is None or not hasattr(_runtime,'maintenance'):raise ValueError('Спочатку запустіть сервер')
        result=_runtime.maintenance.graph_cache.cancel();result['server_running']=True
        return json.dumps(result,ensure_ascii=False)


def preparation_status():
    rt=_runtime
    return json.dumps(rt.maintenance.status() if rt and hasattr(rt,'maintenance') else {'state':'server_stopped'})

def import_prepared(path,sha256):
    from ducksolar.prepared_history import import_package,PreparedHistory
    from ducksolar.history_reader import HistoryReader
    from ducksolar.config import load_config
    cfg=_runtime.device().cfg if _runtime else load_config()
    return json.dumps(import_package(_root,path,sha256,PreparedHistory(HistoryReader(cfg)).model),ensure_ascii=False)

def preparation_model():
    from ducksolar.history_reader import HistoryReader
    from ducksolar.config import load_config
    cfg=_runtime.device().cfg if _runtime else load_config()
    return json.dumps(dict(HistoryReader(cfg).model_signature()),ensure_ascii=False,indent=2)

def check_tariff():
    from dataclasses import asdict
    if not _runtime:raise ValueError('Спочатку запустіть сервер')
    return json.dumps(asdict(_runtime.tariffs.check_for_updates()),ensure_ascii=False)

def self_test():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from ducksolar.config import AppConfig
    from ducksolar.drivers.daxtromn import DaxtromnPI30Driver
    from ducksolar.protocol.pi30 import encode_command
    import cryptography,spake2
    zone=ZoneInfo('Europe/Kyiv')
    c=sqlite3.connect(str(_root/'android-selfcheck.db'))
    try:
        c.execute('CREATE TABLE IF NOT EXISTS probe (id INTEGER PRIMARY KEY, value TEXT)')
        c.execute("INSERT OR REPLACE INTO probe VALUES (1,'persisted')");c.commit()
        assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    finally:c.close()
    driver=DaxtromnPI30Driver(AppConfig(root_dir=str(_root)))
    assert driver.device_code==0x0994 and encode_command('QPIGS') in driver.read_requests
    assert ssl.HAS_TLSv1_3
    out={'python':sys.version.split()[0],'openssl':ssl.OPENSSL_VERSION,
         'tls13':ssl.HAS_TLSv1_3,'sqlite':sqlite3.sqlite_version,'sqlite_integrity':'ok',
         'timezone':str(zone),'cryptography':cryptography.__version__,
         'driver':'daxtromn.pi30.0994','desktop_modules_loaded':
         [x for x in ('tkinter','pystray','PIL') if x in sys.modules]}
    assert not out['desktop_modules_loaded']
    (_root/'SELF_TEST.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    return json.dumps(out)


def update_checkpoint(target):
    with _lock:
        if _runtime is not None:raise RuntimeError('РЎРїРѕС‡Р°С‚РєСѓ Р·СѓРїРёРЅС–С‚СЊ СЃРµСЂРІРµСЂ')
        if _last_stopped:
            for device in _last_stopped.devices.values():
                for owner in (device.writer,device.monitor,device.parameters):
                    thread=getattr(owner,'thread',None)
                    if thread and thread.is_alive():raise RuntimeError('РЎРµСЂРІРµСЂ С‰Рµ Р·Р°РІРµСЂС€СѓС” Р·Р°РїРёСЃ; РѕРЅРѕРІР»РµРЅРЅСЏ РІС–РґРєР»Р°РґРµРЅРѕ')
        from android_update import checkpoint
        return checkpoint(_root,target)

def verify_after_update():
    with _lock:
        from android_update import verify_current
        return verify_current(_root)


def network_changed():
    # Availability callbacks do not restart services or discard history jobs.
    runtime=_runtime
    if not runtime:return False
    from ducksolar.network_info import lan_addresses, logger_route, wifi_snapshot
    addresses=lan_addresses()
    with runtime.network.lock:
        runtime.network.value['lan_ips']=addresses
        runtime.network.value['wifi']=wifi_snapshot()
    try:
        current=logger_route(runtime.gateway.cfg.lwip_ip)
    except OSError:
        # A missing callback or lost Wi-Fi does not justify discarding a live
        # accepted connection. Socket errors own its lifecycle.
        current=None
    previous=getattr(runtime.gateway,'_logger_network_binding',None)
    was_missing=getattr(runtime.gateway,'_logger_route_missing',False)
    runtime.gateway._logger_route_missing=current is None
    if current is not None:
        runtime.gateway._logger_network_binding=current
    changed=previous is not None and current is not None and previous!=current
    if changed:
        runtime.gateway.close_active('Logger Wi-Fi route changed; reconnect logger')
    route=getattr(runtime.gateway,'native_route',None)
    if route and current is not None and (changed or was_missing or previous is None):
        notify=getattr(route,'network_changed',None)
        if notify:notify()
        else:route.wake.set()
    runtime.logs.event('Logger Wi-Fi route checked',code='network.logger_route',previous=previous,current=current,recovery_requested=changed)
    return True


def phone_state(level,scale,plugged,signal):
    from ducksolar.phone_status import update
    update(level,scale,plugged,signal)
    runtime=_runtime
    if runtime:
        import shutil
        try:free=shutil.disk_usage(runtime.cfg.root_dir).free
        except OSError:free=None
        runtime.push_alerts.phone(bool(plugged),free)


def forecast_status(device=''):
    with _lock:
        if _runtime is None:raise ValueError('Спочатку запустіть сервер')
        dev=_runtime.device(device or None);ident=dev.definition.id
        from ducksolar.pv_profiles import profile
        result=_runtime.forecast.status(ident);settings=_runtime.forecast.settings(ident)
        defaults=profile(dev.cfg,ident)
        result.update(device_id=ident,device_name=dev.definition.name,devices=[dict(id=d.definition.id,name=d.definition.name) for d in _runtime.devices.values()],configured=bool(settings))
        result['settings']=settings or dict(location=dev.cfg.weather_location_name,latitude=dev.cfg.weather_latitude,longitude=dev.cfg.weather_longitude,installed_kw=defaults['installed_kw'],tilt_deg=defaults['tilt_deg'],azimuth_deg=defaults['azimuth_deg'])
        return json.dumps(result,ensure_ascii=False,allow_nan=False)

def forecast_train(settings_json,force=False,device=''):
    with _lock:
        if _runtime is None:raise ValueError('Спочатку запустіть сервер')
        ident=_runtime.device(device or None).definition.id
        _runtime.forecast.settings(ident,json.loads(settings_json))
        return json.dumps(_runtime.forecast.start(ident,True,False,bool(force)),ensure_ascii=False,allow_nan=False)

def forecast_cancel(device=''):
    with _lock:
        if _runtime is None:raise ValueError('Спочатку запустіть сервер')
        return json.dumps(_runtime.forecast.cancel(_runtime.device(device or None).definition.id),ensure_ascii=False,allow_nan=False)
