import math
from dataclasses import asdict
from ..core.models import ParameterSpec, PollTask
from ..protocol.pi30 import encode_command, decode_packet, parse_qpigs, QPIRI_FIELDS
from ..energy_model import FlowInput, calculate_flows
from .profiles import current_profile, CURRENT_PROFILE, EXTRA_FIELDS, USER_ENUMS
from ..event_codes import decode_warnings

PROFILE_ID = 'daxtromn.pi30.0994'
MODE_NAMES = {'L': 'Мережа / Utility', 'B': 'АКБ / Battery', 'S': 'Очікування / Standby',
              'P': 'Увімкнення', 'F': 'Помилка', 'H': 'Енергозбереження'}
MODE_KEYS = {key: 'mode.' + key for key in MODE_NAMES}

# IDs and mappings are scoped to the current verified profile, never the core.
METRICS = [
 ('grid.phases.L1.voltage','grid_v','Напруга мережі','V',0,'grid_phase'),
 ('grid.phases.L1.frequency','grid_hz','Частота мережі','Hz',1,'grid_phase'),
 ('output.phases.L1.voltage','output_v','Вихідна напруга','V',2,'output_phase'),
 ('output.phases.L1.frequency','output_hz','Вихідна частота','Hz',3,'output_phase'),
 ('output.apparent_power','output_va','Вихідна повна потужність','VA',4,'system'),
 ('output.active_power','output_w','Вихідна активна потужність','W',5,'system'),
 ('output.load_percent','load_pct','Навантаження','%',6,'system'),
 ('dc.bus_voltage','bus_v','Напруга DC Bus','V',7,'system'),
 ('battery.channels.main.voltage','battery_v','Напруга АКБ','V',8,'battery_channel'),
 ('battery.channels.main.charge_current','charge_a','Струм заряду АКБ','A',9,'battery_channel'),
 ('battery.channels.main.soc','battery_pct','SOC АКБ','%',10,'battery_channel'),
 ('temperature.inverter','temperature_c','Температура інвертора','°C',11,'system'),
 ('pv.inputs.aggregate.current','pv_a','PV струм','A',12,'pv_input'),
 ('pv.inputs.aggregate.voltage','pv_v','PV напруга','V',13,'pv_input'),
 ('battery.scc_voltage','scc_battery_v','Напруга АКБ за SCC','V',14,'system'),
 ('battery.channels.main.discharge_current','discharge_a','Струм розряду АКБ','A',15,'battery_channel'),
 ('device.status_raw','device_status','Статус пристрою (raw)','',16,'system'),
 ('device.service_raw','service_field','Поправка напруги АКБ для вентилятора (код ×10 мВ)','',17,'system'),
 ('device.eeprom_version','eeprom_version','Версія EEPROM','',18,'system'),
 ('pv.total_power','pv_w','Загальна PV потужність','W',19,'system'),
 ('device.extra_status_raw','extra_status','Додатковий статус (raw)','',20,'system'),
]
SETTING_IDS = ['grid.rated_voltage','grid.rated_current','output.rated_voltage','output.rated_frequency',
 'output.rated_current','output.rated_apparent_power','output.rated_active_power','battery.rated_voltage',
 'battery.recharge_voltage','battery.cutoff_voltage','charging.bulk_voltage','charging.float_voltage',
 'battery.type','charging.utility_current_limit','charging.total_current_limit','grid.input_range',
 'output.source_priority','charging.source_priority','parallel.maximum_modules','device.machine_type',
 'device.topology_raw','output.mode_raw','battery.redischarge_voltage']

class DaxtromnPI30Driver:
    id = PROFILE_ID
    protocol = 'PI30'
    device_code = 0x0994
    identity_names = ('QPI', 'QID', 'QMN', 'QVFW', 'QVFW2', 'QPIRI')
    def __init__(self, cfg):
        self.cfg = cfg
        self._grid_identity=({},None)
        self._grid_connection=None;self._grid_mode=None
        self.read_requests = {encode_command(c): c for c in (*self.identity_names, 'QPIGS', 'QMOD', 'QPIWS', 'QFLAG')}
        self.specs = [ParameterSpec(cid, 'parameter.'+cid, label, key, 'QPIGS', unit,
            data_type='string' if key in ('device_status','service_field','eeprom_version','extra_status') else 'number',
            topology=topology, confidence='verified_profile' if not key.endswith('field') and key not in ('device_status','extra_status') else 'unverified',
            source='PI30 profile definitions; verify model compatibility', field_index=i+1, legacy_key=key)
            for cid,key,label,unit,i,topology in METRICS]
        for key,label in [('configuration_changed','Змінено конфігурацію'),('scc_firmware_updated','Оновлено SCC'),('output_enabled','Вихід увімкнений'),('battery_voltage_stable','Напруга АКБ стабільна під час заряду'),('charging_enabled','Зарядна схема активна'),('pv_charging_enabled','PV-заряд активний'),('utility_charging_enabled','Мережевий заряд активний'),('float_stage','Підтримувальний заряд Float'),('switched_on','Інвертор увімкнений')]:
            cid='device.status.'+key
            self.specs.append(ParameterSpec(cid,'parameter.'+cid,label,key,'QPIGS',data_type='boolean',confidence='documented_profile',source='PI30 status definition'))
        for cid, key, label in (
            ('pv.corrected_power','pv_corrected_w','PV скоригована потужність'),
            ('grid.estimated_import_power','estimated_grid_import_w','Орієнтовний імпорт'),
            ('grid.estimated_export_power','estimated_export_w','Орієнтовний експорт'),
            ('battery.estimated_charge_power','battery_charge_w','Орієнтовна потужність заряду')):
            self.specs.append(ParameterSpec(cid,'parameter.'+cid,label,key,'energy_model','W',
                legacy_key=key,confidence='estimated',source='energy model'))
        for i,(cid,(label,unit)) in enumerate(zip(SETTING_IDS, QPIRI_FIELDS), 1):
            enums = {'2':'Solar Only'} if i == 18 else {}
            self.specs.append(ParameterSpec(cid, 'parameter.'+cid, label, 'QPIRI field '+str(i), 'QPIRI', unit,
                data_type='enum' if enums else 'raw', enum_values=enums,
                enum_label_keys={k:'charging.priority.'+k for k in enums}, field_index=i,
                confidence='verified_current_device' if i==18 else 'protocol_family',
                source='PI30 charger-source enum; validate against the detected model' if i==18 else 'PI30 field layout; model validation required'))
        for index,(cid,label,unit) in enumerate(EXTRA_FIELDS,24):
            self.specs.append(ParameterSpec(cid,'parameter.'+cid,label,'QPIRI field '+str(index),
                'QPIRI',unit,data_type='raw',field_index=index,confidence='protocol_family',
                source='Daxtromn profile field layout; select by detected identity'))

    @staticmethod
    def unknown_spec(index):
        return ParameterSpec('raw.qpiri.'+str(index), 'parameter.unknown', 'Невідоме поле QPIRI #'+str(index),
            'QPIRI field '+str(index), 'QPIRI', data_type='raw', field_index=index, confidence='unknown')

    def poll_plan(self):
        return [PollTask('QPIGS',encode_command('QPIGS'),5,20,True),
                PollTask('QMOD',encode_command('QMOD'),5,10), PollTask('QPIWS',encode_command('QPIWS'),5,10)]

    def decode_text(self, payload):
        raw = decode_packet(payload)
        if not raw.startswith(b'('): raise ValueError('Expected PI30 response')
        value = raw[1:].decode('ascii')
        if not value or any(not 32<=ord(c)<127 for c in value): raise ValueError('Invalid PI30 response text')
        if value == 'NAK': raise ValueError('Inverter rejected read command')
        return value

    def decode_response(self,payload,operation):
        value=self.decode_text(payload)
        # CRC-valid echoed commands must never become measurements.
        if value==operation or value in ('ACK','NAK'):raise ValueError('Unexpected command echo/acknowledgement')
        if operation=='QMOD' and value not in MODE_NAMES:raise ValueError('Invalid inverter mode')
        if operation in ('QPIRI','QPIGS'):
            fields=value.split();minimum=23 if operation=='QPIRI' else 17
            if len(fields)<minimum:raise ValueError('Incomplete '+operation+' response')
            try:
                if any(not math.isfinite(float(v)) for v in fields[:16]):raise ValueError('Non-finite response')
            except ValueError:raise ValueError('Invalid '+operation+' numeric fields') from None
        if operation=='QPIWS' and (len(value)!=32 or set(value)-{'0','1'}):raise ValueError('Unsupported QPIWS format')
        if operation=='QFLAG':
            from .parameter_library import flag_values
            flag_values(value)
        if operation=='QPI' and value!='PI30':raise ValueError('Unexpected inverter protocol')
        if operation in ('QVFW','QVFW2') and not value.startswith(('VERFW:','VERFW2:')):raise ValueError('Invalid firmware response')
        return value

    def valid_response(self, payload):
        try: return bool(self.decode_text(payload))
        except (ValueError, UnicodeError): return False

    def set_grid_identity(self,raw,connection):
        self._grid_identity=(dict(raw),connection)

    def prepare_grid_input(self,connection,mode=None):
        self._grid_connection=connection;self._grid_mode=mode

    def input_state(self,values):
        from ..grid_input import classify
        raw,connection=self._grid_identity
        fields=raw.get('QPIRI','').lstrip('(').split()
        apl=(current_profile(raw) and connection==self._grid_connection and len(fields)>15 and fields[15]=='1')
        return classify(values,self.cfg,allow_low=apl,mode=self._grid_mode)

    def decode_telemetry(self, text):
        q = parse_qpigs(text)
        if any(isinstance(v,(int,float)) and not math.isfinite(v) for v in asdict(q).values()):
            raise ValueError("Non-finite telemetry value")
        input_state=self.input_state(asdict(q));available=input_state['available']
        flow = calculate_flows(FlowInput(q.pv_w,q.output_w,q.battery_v,q.charge_a,available),
            pv_factor=self.cfg.pv_correction_factor, inverter_self_w=self.cfg.inverter_self_consumption_w)
        return {**asdict(q), 'grid_available':int(available), 'grid_input_state':input_state, 'battery_charge_w':flow.battery_charge_w,
            'pv_corrected_w':flow.pv_corrected_w, 'estimated_grid_import_w':flow.grid_import_w,
            'estimated_export_w':flow.export_w}

    def decode_native_telemetry(self, values, source='ESS'):
        values=dict(values)
        input_state=self.input_state(values);available=input_state['available']
        flow=calculate_flows(FlowInput(values['pv_w'],values['output_w'],values['battery_v'],values['charge_a'],available),
            pv_factor=self.cfg.pv_correction_factor,inverter_self_w=self.cfg.inverter_self_consumption_w)
        values.update(grid_available=int(available),grid_input_state=input_state,battery_charge_w=flow.battery_charge_w,
            pv_corrected_w=flow.pv_corrected_w,estimated_grid_import_w=flow.grid_import_w,
            estimated_export_w=flow.export_w,measurement_source='ESS native / locally cross-checked',
            native_confidence='protocol_family',native_origin=source)
        # Unsupported fields are absent, never zero or silently copied from older PI30 data.
        return values

    def augment_native(self,values,aux,identity):
        values=dict(values,native_profile_confirmed=current_profile(identity))
        if current_profile(identity) and isinstance(aux.get('temperature_c'),(int,float)):
            values=dict(values,temperature_c=aux['temperature_c'],temperature_received_monotonic=aux.get('_received_monotonic'),temperature_source='ESS/4557; profile correlation 2026-10-18')
        return values

    def decode_update(self, task, text):
        if task.telemetry: return self.decode_telemetry(text)
        if task.name == 'QMOD': return {'mode':MODE_NAMES.get(text,text), 'mode_code':text, 'mode_label_key':MODE_KEYS.get(text,'mode.unknown')}
        return {'warnings':text}

    def parameter_rows(self, text, identity_raw=None):
        result=[]
        profile=current_profile(identity_raw or {})
        specs={s.field_index:s for s in self.specs if s.command=='QPIRI'}
        for index, raw in enumerate(text.lstrip('(').split(), 1):
            spec=specs.get(index,self.unknown_spec(index))
            if index>=26 and not profile:spec=self.unknown_spec(index)
            enums=USER_ENUMS.get(index,{}) if profile else spec.enum_values
            confidence=('unknown' if index>=26 else 'verified_current_device' if not enums or raw in enums else 'protocol_family') if profile else spec.confidence
            result.append({**spec.to_dict(), 'index':str(index), 'name':spec.ui_name,
                'value':raw, 'raw_value':raw, 'raw_code':raw,
                'display_value':enums.get(raw,raw),
                'confidence':confidence,'source':'Detected-model PI30 profile mapping' if profile else spec.source,
                'display_confidence':confidence,'value_confidence':'unknown' if enums and raw not in enums else confidence})
        return result

    def parameter_rows_from_raw(self, raw):
        return self.parameter_rows(raw.get('QPIRI',''),raw)

    def parameter_catalog(self,raw):
        present={row['canonical_id']:row for row in self.parameter_rows_from_raw(raw)}
        result=[]
        for spec in self.specs:
            if spec.command!='QPIRI':continue
            row=present.pop(spec.canonical_id,None)
            item=dict(row or spec.to_dict())
            if spec.field_index>=26 and not current_profile(raw):
                spec=self.unknown_spec(spec.field_index)
                row=present.pop(spec.canonical_id,None)
                item=dict(row or spec.to_dict())
            item.update(index=str(spec.field_index),name=(row or {}).get('name',spec.ui_name),present=row is not None,
                readable=True,writable=False,write_reason='Команду або допустимі значення для цього firmware не підтверджено',
                allowed_values_confirmed=False,allowed_note='Повний перелік допустимих значень не підтверджено')
            if row is None:item.update(value=None,raw_value=None,display_value='—',value_confidence='unavailable')
            if spec.canonical_id=='charging.source_priority':
                item['allowed_note']='Поточний профіль: 0 = Solar first; 1 = Solar + Utility; 2 = Only Solar. Команди запису перевіряються окремо'
            from .parameter_library import RULES, matches, allowed_note, SOURCE
            rule=RULES.get(spec.canonical_id)
            if rule and matches(raw) and row:
                item.update(writable=True,allowed_values_confirmed=True,write_rule=rule,
                    allowed_note=allowed_note(rule),source=SOURCE,
                    write_reason='Запис із підтвердженням та контрольним читанням; без автоматичних повторів')
                if 'enum' in rule and not current_profile(raw):
                    item['display_value']=rule['enum'].get(str(int(float(item['raw_value']))),item['raw_value'])
            result.append(item)
        for row in present.values():
            result.append(dict(row,present=True,readable=True,writable=False,allowed_values_confirmed=False,allowed_note='Не підтверджено'))
        from .parameter_library import FLAG_SETTINGS,flag_values
        try:flags=flag_values(raw.get('QFLAG',''))
        except ValueError:flags={}
        for number,(key,(letter,title)) in enumerate(FLAG_SETTINGS.items(),10001):
            value=flags.get(key)
            result.append(dict(canonical_id=key,index=str(number),name=title,unit='',raw_value=value,
                display_value=RULES[key]['enum'].get(value,'—'),present=value is not None,readable=True,
                writable=matches(raw) and value is not None,write_rule=RULES[key],
                allowed_values_confirmed=True,allowed_note=allowed_note(RULES[key]),
                write_reason='Потрібна свіжа відповідь QFLAG' if value is None else 'Запис із контрольним читанням',
                confidence='protocol_family',source=SOURCE))
        return sorted(result,key=lambda row:int(row['index']))

    def identity(self, raw):
        serial=str(raw.get('QID','')).strip().lstrip('(').rstrip(')\r\n').strip()
        if not serial.isascii() or not serial.isalnum() or serial.upper() in ('NAK','ACK'):serial=''
        return {'serial':serial,'protocol':raw.get('QPI',''),'model':raw.get('QMN',''),
            'firmware':raw.get('QVFW',''),'firmware_secondary':raw.get('QVFW2','')}

    def descriptor(self, definition, raw):
        return {'device_id':definition.id,'name':definition.name,'logger_id':definition.logger_id,
            'profile_id':CURRENT_PROFILE if current_profile(raw) else 'daxtromn.pi30.reference',
            'profile_confirmed':current_profile(raw),'scope':'Daxtromn + EyBond',
            'manufacturer':'DAXTROMN','model':raw.get('QMN') or None, 'device_family':'PI30 Solar',
            'protocol':self.protocol,'driver':self.id,'firmware':self.identity(raw),
            'phase_topology':'single_phase','phase_count':1,'mppt_count':1 if current_profile(raw) else None,'battery_channels':1,
            'available_metrics':[s.canonical_id for s in self.specs if s.command!='QPIRI'],
            'available_settings':[r['canonical_id'] for r in self.parameter_rows_from_raw(raw) if r['value_confidence'] not in ('unknown','unverified')],
            'readable_parameters':[r['canonical_id'] for r in self.parameter_rows_from_raw(raw)], 'writable_parameters':[r['canonical_id'] for r in self.parameter_catalog(raw) if r['writable']],
            'supports_own_writes':any(r['writable'] for r in self.parameter_catalog(raw)),'supports_reactive_power':False,'supports_line_voltage':False,
            'supports_phase_current':False,'supports_grid_export':None,'supports_bms':None,
            'topology':{'grid':{'phases':[{'id':'L1'}]},'output':{'phases':[{'id':'L1'}]},
                'pv':{'mppts':[],'inputs':[{'id':'aggregate','scope':'reported_aggregate'}]},
                'battery':{'modules':[],'channels':[{'id':'main'}]}},
            'topology_source':'Current installation; QPIGS exposes aggregate PV, not MPPT count'}

    def normalized(self, values):
        measurements={s.canonical_id:{'value':values[s.legacy_key], 'unit':s.unit, 'confidence':s.confidence,
            'source':s.command, 'quality':'good'} for s in self.specs if s.legacy_key in values}
        for key,cid in [('estimated_grid_import_w','grid.estimated_import_power'),('estimated_export_w','grid.estimated_export_power'),
                        ('pv_corrected_w','pv.corrected_power'),('battery_charge_w','battery.estimated_charge_power')]:
            if key in values: measurements[cid]={'value':values[key],'unit':'W','confidence':'estimated','source':'energy_model','quality':'good'}
        if values.get('native_confidence'):
            for item in measurements.values():
                if item['source']=='QPIGS':
                    item.update(confidence='verified_current_device' if values.get('native_profile_confirmed') else 'protocol_family',source=values.get('native_origin','ESS')+'/4501; cross-checked PI30')
        from ..telemetry_quality import power_factor
        pf,reason=power_factor(values.get('output_w'),values.get('output_va'))
        measurements['output.power_factor']=dict(value=pf,unit='',quality='good' if pf is not None else 'unavailable',
            invalidated=pf is None,precision=2,confidence='calculated',source='same_acquisition.P/S',quality_reason=reason,note='PF = P / S; не фазовий cos φ')
        # Preserve raw S/P, but an inconsistent apparent power must not feed
        # RMS-current or power-factor estimates as though it were valid.
        va=values.get('output_va');watts=values.get('output_w')
        if isinstance(va,(int,float)) and isinstance(watts,(int,float)) and watts>va:
            measurements.get('output.apparent_power',{}).update(quality='good',calculation_valid=False,quality_reason='active_power_exceeds_apparent',warning='Інвертор повідомив ВА менше Вт; не використовується для розрахунку струму')
        if 'temperature_c' in values and values.get('temperature_source'):
            measurements.get('temperature.inverter',{}).update(confidence='verified_current_device',source=values['temperature_source'])
        # Decode documented statuses separately; retain original bit strings.
        bits=str(values.get('device_status',''))
        names={1:'configuration_changed',2:'scc_firmware_updated',3:'output_enabled',4:'battery_voltage_stable',5:'charging_enabled',6:'pv_charging_enabled',7:'utility_charging_enabled'}
        if len(bits)==8 and set(bits)<={'0','1'}:
            for index,name in names.items():
                measurements['device.status.'+name]=dict(value=bits[index]=='1',unit='',confidence='documented_profile',quality='good',source='QPIGS.status')
        extra=str(values.get('extra_status',''))
        if len(extra)==3 and set(extra)<={'0','1'}:
            for index,name in [(0,'float_stage'),(1,'switched_on')]:
                measurements['device.status.'+name]=dict(value=extra[index]=='1',unit='',confidence='documented_profile',quality='good',source='QPIGS.extra_status')
        def take(key): return values.get(key)
        return {'metrics':measurements,
            'grid':{'phases':[{'id':'L1','voltage':take('grid_v'),'frequency':take('grid_hz')}], 'available':take('grid_available'),**values.get('grid_input_state',{})},
            'output':{'phases':[{'id':'L1','voltage':take('output_v'),'frequency':take('output_hz')}], 'active_power':take('output_w')},
            'pv':{'mppts':[],'inputs':[{'id':'aggregate','voltage':take('pv_v'),'current':take('pv_a')}], 'total_power':take('pv_w')},
            'battery':{'modules':[],'channels':[{'id':'main','voltage':take('battery_v'),'soc':take('battery_pct'),
                'charge_current':take('charge_a'),'discharge_current':take('discharge_a')}]}}
