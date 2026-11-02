"""Validate acquisition values before publication, history and automation."""
import math

def number(value):
    return type(value) in (int, float) and math.isfinite(value)

def power_factor(watts, apparent):
    if not number(watts) or not number(apparent):return None, 'missing_or_nonfinite'
    if watts < 0 or apparent <= 0:return None, 'invalid_power'
    if watts > apparent:return None, 'active_power_exceeds_apparent'
    return watts / apparent, ''

def add_power_factor(values):
    value, reason = power_factor(values.get('output_w'), values.get('output_va'))
    values.update(output_pf=value, output_pf_reason=reason)
    return values

class SocGuard:
    """Native anomalies need direct PI30 corroboration; never substitute a SOC.

    Real low SOC on the first direct read is usable. A sudden direct jump is
    accepted only after another acquisition confirms it, including a preceding
    rejected native reading. State is scoped to the physical connection.
    """
    def __init__(self):
        self.connection=None;self.last=None;self.pending=None;self.pending_direct=False

    def check(self, value, native, connection, now):
        if connection != self.connection:
            self.connection=connection;self.last=None;self.pending=None;self.pending_direct=False
        if not number(value) or not 0 <= value <= 100:return None, 'invalid_soc'
        jump=self.last is not None and abs(value-self.last[0]) > max(10, (now-self.last[1]) / 60)
        initial_low=self.last is None and native and value <= 30
        confirmed=self.pending is not None and abs(value-self.pending[0]) <= 2 and now > self.pending[1] and now-self.pending[1] <= 90
        if (jump or initial_low) and not (not native and confirmed):
            self.pending=(value,now);self.pending_direct=True
            return None, 'soc_confirmation_required'
        self.last=(value,now);self.pending=None;self.pending_direct=False
        return value, ''
