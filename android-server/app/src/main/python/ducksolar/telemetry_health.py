"""Separate acquisition freshness from connection loss; never renew data age."""
def health(linked, same_connection, age, fresh_limit, grace=15, reply_age=None):
    acquired=linked and same_connection and age is not None and age>=0
    fresh=bool(acquired and age<fresh_limit)
    replying=reply_age is not None and 0<=reply_age<fresh_limit
    connected=bool(acquired and (age<fresh_limit+grace or replying))
    status='fresh' if fresh else 'delayed' if connected else 'awaiting' if linked and (age is None or not same_connection) else 'offline'
    return dict(fresh=fresh,connected=connected,status=status)

class PowerConfirmation:
    """Repeated native P>S is one episode, independent of direct confirmations.

    Normal periodic PI30 reads also confirm it. A dedicated read is requested
    only after 30 s without a direct acquisition and at most once per 120 s.
    Sixty seconds of coherent native samples closes the episode.
    """
    def __init__(self):self.reset(None)
    def reset(self,connection):
        self.connection=connection;self.active=False;self.pending=False
        self.last_direct=float('-inf');self.last_attempt=float('-inf')
        self.last_log=float('-inf');self.good_since=None;self.count=0
    def observe(self,inconsistent,native,connection,now):
        if connection!=self.connection:self.reset(connection)
        if not native:
            self.last_direct=max(self.last_direct,now);self.pending=bool(inconsistent)
            return None
        if inconsistent:
            self.good_since=None;self.pending=True;self.count+=1
            if not self.active:
                self.active=True;self.last_log=now;return 'started'
            if now-self.last_log>=300:self.last_log=now;return 'summary'
        elif self.active:
            if self.good_since is None:self.good_since=now
            if now-self.good_since>=60:
                self.active=False;self.pending=False;self.good_since=None;return 'cleared'
        return None
    def due(self,now):
        if self.pending and now-self.last_direct>=30 and now-self.last_attempt>=120:
            self.last_attempt=now;return True
        return False
