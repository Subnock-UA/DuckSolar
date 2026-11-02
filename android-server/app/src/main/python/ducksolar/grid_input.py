"""Grid presence is distinct from voltage quality and accepted AC input.

Only extend the old operating envelope when the verified APL profile (live),
 or actual tracked low-voltage bypass samples (history), justify it. No writes.
"""
import math

def number(value):
    return float(value) if type(value) in (int,float) and math.isfinite(value) else None

def classify(values,cfg,allow_low=False,mode=None):
    v=number(values.get('grid_v'));hz=number(values.get('grid_hz'))
    present=v is not None and v>20
    regular=(v is not None and hz is not None and cfg.grid_present_min_v<=v<=cfg.grid_present_max_v
             and cfg.grid_present_min_hz<=hz<=cfg.grid_present_max_hz)
    reason='configured_range' if regular else 'absent' if not present else 'not_accepted'
    accepted=regular
    if not accepted and allow_low and present and hz is not None and 90<=v<cfg.grid_present_min_v and v<=280 and cfg.grid_present_min_hz<=hz<=cfg.grid_present_max_hz:
        output=number(values.get('output_v'));output_hz=number(values.get('output_hz'))
        discharge=number(values.get('discharge_a'))
        tracking=(output is not None and output_hz is not None and abs(output-v)<=max(3.,v*.02)
                  and abs(output_hz-hz)<=.5)
        # A live QMOD can lag a transfer; fresh bypass plus zero discharge
        # independently proves accepted AC. A residual input with 230V battery
        # output does not qualify. Never infer grid acceptance from PUSH alone.
        if tracking and (mode=='L' or discharge==0):
            accepted=True;reason='accepted_low_voltage_bypass'
    status='unavailable' if v is None else 'absent' if not present else 'low' if v<cfg.grid_present_min_v else 'high' if v>cfg.grid_present_max_v else 'normal'
    return dict(available=bool(accepted),voltage_present=present if v is not None else None,voltage_status=status,acceptance_reason=reason)
