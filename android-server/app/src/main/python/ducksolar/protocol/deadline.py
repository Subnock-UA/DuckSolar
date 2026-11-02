"""One deadline covers queue admission, ESS arbitration and the wire reply."""
from contextvars import ContextVar
deadline=ContextVar('ducksolar_protocol_deadline',default=None)

def admission_end(now,reply_timeout,outer):
    return min(now+14,outer-reply_timeout) if outer is not None else now+14

def learned_duration(previous,elapsed):
    # An occasional slow reply must not teach an 8-second forecast exclusion
    # window, starving local requests before a predicted ESS request arrives.
    return min(3,max(.1,.8*previous+.2*elapsed))
