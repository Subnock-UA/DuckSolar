"""API compatibility is independent of application release numbers."""
API_VERSIONS=(3,)
CAPABILITIES=('energy.month.compact.v1','api.v3','parameters.readback.retry','events.decoded.v1','diagnostics.v1','profiles.daxtromn.eybond.v1','notifications.push.v1','live.delta.v1','live.idle.v1','notifications.extended.v1')
def check_required(required):
    from .client_sessions import SessionError
    if not isinstance(required,list) or len(required)>32 or any(not isinstance(x,str) for x in required):
        raise ValueError('Invalid capability request')
    missing=set(required)-set(CAPABILITIES)
    if missing:raise SessionError('Оновіть Server: відсутні можливості '+', '.join(sorted(missing)),409,'api.incompatible')
