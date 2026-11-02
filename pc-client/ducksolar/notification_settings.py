"""Validated, backward-compatible opt-in alert settings shared by client/server."""
LEGACY=dict(grid_lost=True,grid_restored=True,server_battery=True,inverter_battery=True,server_battery_threshold=50)
GROUPS=('inverter_connection','server_connection','grid_voltage','overload','over_temperature','critical_battery','server_power','storage')
DEFAULTS={**LEGACY,**dict.fromkeys(GROUPS,False), 'connection_delay_s':90,'grid_voltage_min':180,'grid_voltage_max':260,'condition_delay_s':30,'overload_pct':90,'temperature_c':65,'critical_battery_pct':15,'power_delay_s':60,'storage_min_mb':256}
RANGES={'server_battery_threshold':(1,99),'connection_delay_s':(30,600),'grid_voltage_min':(80,240),'grid_voltage_max':(200,300),'condition_delay_s':(5,300),'overload_pct':(50,100),'temperature_c':(40,100),'critical_battery_pct':(1,29),'power_delay_s':(10,600),'storage_min_mb':(64,4096)}
KIND_GROUP={**{k:k for k in LEGACY if k!='server_battery_threshold'},'inverter_lost':'inverter_connection','inverter_restored':'inverter_connection','server_lost':'server_connection','server_restored':'server_connection','grid_voltage_bad':'grid_voltage','grid_voltage_ok':'grid_voltage','overload_high':'overload','overload_ok':'overload','temperature_high':'over_temperature','temperature_ok':'over_temperature','battery_critical':'critical_battery','battery_critical_ok':'critical_battery','server_unplugged':'server_power','server_plugged':'server_power','storage_low':'storage','storage_ok':'storage','storage_error':'storage'}
def validate(value):
    if not isinstance(value,dict) or set(value)-set(DEFAULTS):raise ValueError('Invalid notification settings')
    result={**DEFAULTS,**value}
    for key,default in DEFAULTS.items():
        v=result[key]
        if key in RANGES:
            lo,hi=RANGES[key]
            if type(v) is not int or not lo<=v<=hi:raise ValueError(f'{key}: {lo}..{hi}')
        elif type(v) is not bool:raise ValueError('Expected notification switch')
    if result['grid_voltage_min']>=result['grid_voltage_max']:raise ValueError('Invalid voltage range')
    return result
