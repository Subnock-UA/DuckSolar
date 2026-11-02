"""Negotiated lossless live updates. Each new stream starts with a full state."""
import copy

PROTOCOL='delta1'

def differences(old,new,path=()):
    changes=[];removed=[]
    if isinstance(old,dict) and isinstance(new,dict):
        for key in old.keys()-new.keys():removed.append(list(path+(key,)))
        for key,value in new.items():
            if key not in old:changes.append([list(path+(key,)),value])
            elif old[key]!=value:
                if isinstance(old[key],dict) and isinstance(value,dict):
                    c,r=differences(old[key],value,path+(key,));changes.extend(c);removed.extend(r)
                else:changes.append([list(path+(key,)),value])
    return changes,removed

class Encoder:
    def __init__(self):self.previous=None
    def packet(self,state):
        previous=self.previous
        self.previous=state
        if previous is None or previous.get('session_id')!=state.get('session_id'):
            return dict(live=PROTOCOL,type='full',state=state)
        changes,removed=differences(previous,state)
        if len(changes)+len(removed)>8192:
            return dict(live=PROTOCOL,type='full',state=state)
        return dict(live=PROTOCOL,type='patch',session_id=state['session_id'],base=previous['sequence'],
                    sequence=state['sequence'],changes=changes,removed=removed)

class Decoder:
    def __init__(self):self.state=None
    def accept(self,packet):
        if packet.get('live')!=PROTOCOL:
            return packet
        if packet.get('type')=='full':
            state=packet.get('state')
            if not isinstance(state,dict) or not isinstance(state.get('session_id'),str) or type(state.get('sequence')) is not int:
                raise ValueError('Invalid full live state')
            self.state=copy.deepcopy(state)
        elif packet.get('type')=='patch':
            if self.state is None or packet.get('session_id')!=self.state.get('session_id') or packet.get('base')!=self.state.get('sequence'):
                raise ValueError('Live baseline mismatch; reconnect required')
            changes=packet.get('changes');removed=packet.get('removed')
            if not isinstance(changes,list) or not isinstance(removed,list) or len(changes)+len(removed)>8192:
                raise ValueError('Invalid live patch')
            def target(path):
                if not isinstance(path,list) or not 1<=len(path)<=32 or any(not isinstance(k,str) for k in path):
                    raise ValueError('Invalid live path')
                node=self.state
                for key in path[:-1]:
                    node=node.get(key)
                    if not isinstance(node,dict):raise ValueError('Missing live path')
                return node,path[-1]
            for path in removed:
                node,key=target(path);node.pop(key,None)
            for change in changes:
                if not isinstance(change,list) or len(change)!=2:raise ValueError('Invalid live change')
                node,key=target(change[0]);node[key]=copy.deepcopy(change[1])
            if self.state.get('sequence')!=packet.get('sequence'):raise ValueError('Invalid live sequence')
        else:raise ValueError('Unknown live packet')
        return copy.deepcopy(self.state)
