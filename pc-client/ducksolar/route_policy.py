"""Connection health, independent of Android and transport credentials."""
import time
class RoutePolicy:
    def __init__(self, clock=time.monotonic):
        self.clock=clock; self.active=None; self.failures={}; self.until={}; self.attempt_started=0
    def ordered(self, urls):
        now=self.clock(); urls=list(dict.fromkeys(urls))
        ready=[u for u in urls if self.until.get(u,0)<=now]
        return sorted(ready,key=lambda u:0 if u==self.active else 1)
    def failed(self,url):
        n=self.failures.get(url,0)+1;self.failures[url]=n
        self.until[url]=self.clock()+min(180,30*2**min(n-1,3))
    def success(self,url):
        self.active=url;self.failures.pop(url,None);self.until.pop(url,None)
    def network_changed(self):
        # A new physical route may make a previously unreachable endpoint usable.
        self.until.clear()
