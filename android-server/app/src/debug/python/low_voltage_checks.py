import json
from ducksolar.config import AppConfig
from ducksolar.drivers.daxtromn import DaxtromnPI30Driver
from ducksolar.grid_flow import select_grid_flows
from ducksolar.monitor_metrics import add_metrics

def run():
 raw=dict(QPI='PI30',QMN='VMII-NXPW5KW',QVFW='VERFW:00074.11',QPIRI='230.0 26.9 230.0 50.0 26.9 6200 6200 48.0 46.0 40.0 55.2 54.0 2 060 120 1 1 1 1 01 0 0 57.0 0 1 46.0 22 44.0')
 d=DaxtromnPI30Driver(AppConfig());d.set_grid_identity(raw,'same');d.prepare_grid_input('same','L')
 v=dict(grid_v=173.1,grid_hz=49.9,output_v=173.1,output_hz=49.9,pv_w=1,battery_v=54.2,battery_pct=95,charge_a=56,discharge_a=0,output_w=2562,output_va=2579,load_pct=41,pv_v=35.9)
 decoded=d.decode_native_telemetry(v);assert decoded['grid_available']==1
 n=select_grid_flows(d.normalized(decoded));n,_=add_metrics(n,{'available_metrics':[],'phase_count':1},d.cfg)
 assert abs(n['metrics']['grid.import_power']['value']-5651.18)<.001
 assert abs(n['metrics']['grid.phases.L1.current']['value']-32.6469093)<.001
 assert n['grid']['voltage_status']=='low'
 d.prepare_grid_input('new','L');assert d.decode_native_telemetry(v)['grid_available']==0
 return json.dumps({'passed':True,'import_w':5651.18})
