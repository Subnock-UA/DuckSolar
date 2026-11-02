"""Additional display metrics derived on Server from the selected flow sources."""
import math

def add_metrics(normalized,descriptor,cfg):
    from .display_metrics import usable,calculated
    metrics=normalized.setdefault('metrics',{})
    def value(key):
        item=metrics.get(key,{})
        v=item.get('value')
        return v if usable(item) else None
    def add(key,label,v,unit,inputs=(),**metadata):
        metrics[key]={**calculated(v,unit,[metrics.get(x,{}) for x in inputs],'energy_model'),**metadata}
        if key not in descriptor['available_metrics']:descriptor['available_metrics'].append(key)
        descriptor.setdefault('metric_definitions',[]).append(dict(canonical_id=key,ui_name=label,unit=unit))
    pv=value('pv.corrected_power');load=value('output.active_power');charge=value('battery.estimated_charge_power')
    coverage=None
    if None not in (pv,load,charge):
        remaining=max(0,pv-min(pv,max(0,charge))-max(0,cfg.inverter_self_consumption_w))
        coverage=max(0,min(100,remaining/load*100)) if load>0 else 0
    add('output.pv_coverage_percent','Покриття навантаження з PV',coverage,'%',inputs=('pv.corrected_power','output.active_power','battery.estimated_charge_power'))
    imports=value('grid.import_power');exports=value('grid.export_power')
    if imports is None or exports is None:direction='unknown'
    elif imports>0 and exports>0:direction='mixed'
    elif imports>0:direction='import'
    elif exports>0:direction='export'
    else:direction='none'
    phases=normalized.get('grid',{}).get('phases',[])
    # Do not infer individual phase currents from aggregate power on multi-phase devices.
    if descriptor.get('phase_count')==1 and phases:
        key='grid.phases.'+phases[0]['id']+'.current'
        if key in metrics and value(key) is not None:
            metrics[key]['direction']=direction
        else:
            voltage=phases[0].get('voltage');current=None
            if type(voltage) in (int,float) and voltage>0 and direction not in ('unknown','mixed'):
                current=max(imports,exports)/voltage
            if normalized.get('grid',{}).get('available') is False:current=0;direction='none'
            add(key,'Струм (оцінка P/U)',current,'A',inputs=('grid.import_power','grid.export_power','grid.phases.'+phases[0]['id']+'.voltage'),direction=direction)
    return normalized,descriptor
