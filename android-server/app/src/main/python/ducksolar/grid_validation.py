"""Stateful sensor plausibility checks, advanced only by new telemetry polls.

Drivers supply grid.measurement_context: scope_matches, independent_balance,
ac_connected, export_allowed, battery_present and optional sensor_status.
Unknown operating states never count as evidence against a measured zero.
"""
import copy
import math
from .grid_flow import valid_metric, expand_signed_measurements


class GridMeasurementValidator:
    def __init__(self, cfg, event=None):
        self.cfg = cfg
        self.event = event
        self.state = {}
        self.connection_id = None

    def reset(self, connection_id):
        self.state.clear()
        self.connection_id = connection_id

    def _number(self, metrics, key, unit, now):
        item = metrics.get(key)
        if not valid_metric(item, unit, now):
            return None
        if item.get('depends_on_grid_measurement'):
            return None
        return item['value']

    def _balance(self, normalized, now):
        metrics = normalized.get('metrics', {})
        context = normalized.get('grid', {}).get('measurement_context', {})
        reasons = []
        if context.get('scope_matches') is not True:
            reasons.append('measurement_scope_unconfirmed')
        if context.get('independent_balance') is not True:
            reasons.append('independent_balance_unconfirmed')
        if context.get('ac_connected') is not True:
            reasons.append('ac_connection_unconfirmed')
        if context.get('mode') not in ('grid_connected','hybrid','bypass'):
            reasons.append('operating_mode_unconfirmed_or_isolated')
        voltage = self._number(metrics, 'grid.input_voltage', 'V', now)
        if voltage is None:
            phases = [item for key,item in metrics.items() if key.startswith('grid.phases.') and key.endswith('.voltage')]
            if phases and all(valid_metric(item, 'V', now) for item in phases):
                values = [item['value'] for item in phases]
                # A disconnected phase cannot be used to infer its grid flow.
                voltage = min(values)
        if voltage is None or not self.cfg.grid_present_min_v <= voltage <= self.cfg.grid_present_max_v:
            reasons.append('ac_voltage_absent_or_invalid')
        pv = self._number(metrics, 'pv.total_power', 'W', now)
        load = self._number(metrics, 'output.active_power', 'W', now)
        charge = self._number(metrics, 'battery.charge_power', 'W', now)
        discharge = self._number(metrics, 'battery.discharge_power', 'W', now)
        if context.get('battery_present') is False:
            charge = discharge = 0.0
        elif context.get('battery_present') is True:
            # Full per-channel V/I readings are an independent alternative to W.
            channels = normalized.get('battery', {}).get('channels', [])
            if charge is None or discharge is None:
                charge_sum = discharge_sum = 0.0
                complete = bool(channels)
                for channel in channels:
                    prefix = 'battery.channels.'+str(channel['id'])+'.'
                    v = self._number(metrics,prefix+'voltage','V',now)
                    a = self._number(metrics,prefix+'charge_current','A',now)
                    b = self._number(metrics,prefix+'discharge_current','A',now)
                    if None in (v,a,b):
                        complete = False
                        break
                    charge_sum += v*a
                    discharge_sum += v*b
                if complete:
                    if charge is None: charge = charge_sum
                    if discharge is None: discharge = discharge_sum
        else:
            reasons.append('battery_topology_unconfirmed')
        if None in (pv, load, charge, discharge):
            reasons.append('balance_inputs_missing_or_invalid')
        # Prevent independently fresh but unsynchronized samples from comparing.
        stamps = []
        from datetime import datetime
        for key,item in metrics.items():
            relevant = key in ('pv.total_power','output.active_power','battery.charge_power','battery.discharge_power','grid.measured_import_power','grid.measured_export_power','grid.measured_net_power','grid.input_voltage') or (key.startswith('battery.channels.') and key.endswith(('.voltage','.charge_current','.discharge_current')))
            if relevant and valid_metric(item,item.get('unit'),now) and item.get('timestamp'):
                stamp = datetime.fromisoformat(item['timestamp'])
                stamps.append(stamp.timestamp())
        if stamps and max(stamps)-min(stamps) > max(2.0,self.cfg.poll_interval_s*2):
            reasons.append('balance_samples_unsynchronized')
        details = dict(pv_w=pv,load_w=load,charge_w=charge,discharge_w=discharge,ac_input_v=voltage,
            ac_connected=context.get('ac_connected'),export_allowed=context.get('export_allowed'),mode=context.get('mode'),
            scope_matches=context.get('scope_matches'),independent_balance=context.get('independent_balance'))
        if reasons:
            return None, None, details, reasons
        # Use actual PV, without the legacy correction factor.
        demand = load+charge+max(0.0,self.cfg.inverter_self_consumption_w)
        supply = pv+discharge
        details.update(demand_w=demand,supply_w=supply,inverter_self_w=self.cfg.inverter_self_consumption_w)
        return demand, supply, details, []

    def process(self, normalized, now, elapsed_s, connection_id):
        if connection_id != self.connection_id:
            self.reset(connection_id)
        result = expand_signed_measurements(normalized, now)
        context = result.get('grid', {}).get('measurement_context', {})
        demand, supply, details, missing = self._balance(result, now)
        diagnostics = {}
        for direction in ('import','export'):
            key = 'grid.measured_'+direction+'_power'
            item = result.get('metrics',{}).get(key)
            if not isinstance(item,dict):
                continue
            state = self.state.setdefault(direction,dict(suspect=False,pending=None,recovery=None,last=None))
            gap = state['last'] is not None and elapsed_s-state['last'] > max(30,self.cfg.poll_interval_s*3+self.cfg.socket_timeout_s)
            if gap:
                state['pending'] = state['recovery'] = None
            state['last'] = elapsed_s
            sensor = item.get('sensor_status',context.get('sensor_status'))
            valid = valid_metric(item,'W',now)
            sensor_bad = sensor in ('missing','fault','disabled','unknown','unconfirmed')
            zero = valid and abs(item['value']) <= 1e-6
            balance_ok = not missing
            allowed = direction == 'import' or context.get('export_allowed') is True
            high, low = (demand,supply) if direction=='import' else (supply,demand)
            contradiction = bool(zero and balance_ok and allowed and high > low*1.2 and high-low > 100.0)
            if contradiction:
                if state['pending'] is None: state['pending'] = elapsed_s
                state['recovery'] = None
                if elapsed_s-state['pending'] >= 30.0: state['suspect'] = True
            else:
                state['pending'] = None
                # Missing evidence does not automatically restore a rejected zero.
                healthy = valid and not sensor_bad and (not zero or (balance_ok and (not allowed or not contradiction)) or
                    (context.get('ac_connected') is False and zero))
                if state['suspect'] and healthy:
                    if state['recovery'] is None: state['recovery'] = elapsed_s
                    if elapsed_s-state['recovery'] >= 30.0:
                        state['suspect'] = False
                        state['recovery'] = None
                else: state['recovery'] = None
            reason = 'sensor_'+sensor if sensor_bad else 'zero_balance_mismatch' if state['suspect'] else ''
            status = 'rejected' if reason else 'pending' if contradiction else 'accepted' if valid else 'unverified'
            diag = dict(status=status,reason=reason,pending_s=round(elapsed_s-state['pending'],3) if state['pending'] is not None else 0,
                measured_w=item.get('value'),sensor_status=sensor,relative_threshold_pct=20,absolute_threshold_w=100,
                persistence_s=30,checks_unavailable=missing,**details)
            diagnostics[direction] = diag
            if reason:
                item['driver_quality'] = item.get('quality','unknown')
                item['quality'] = 'suspect' if reason=='zero_balance_mismatch' else 'invalid'
                item['validation_reason'] = reason
                # A stuck counter from the same/unknown sensor must not bypass rejection.
                counter = result['metrics'].get('grid.'+direction+'_energy_total')
                if isinstance(counter,dict) and counter.get('independent_sensor') is not True:
                    counter['driver_quality'] = counter.get('quality','unknown')
                    counter['quality'] = 'suspect'
                    counter['validation_reason'] = reason
            transition = (status,reason,tuple(missing))
            if state.get('reported') != transition:
                if self.event:
                    self.event('Grid measurement '+direction+' '+status,code='grid.measurement.'+status,
                        direction=direction,connection_id=connection_id,**diag)
                state['reported'] = transition
        result.setdefault('grid',{})['flow_validation'] = diagnostics
        return result
