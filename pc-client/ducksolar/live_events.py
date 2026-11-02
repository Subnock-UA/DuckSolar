"""Parse complete SSE events, keeping partial transport data out of JSON."""
import json
from .client_transport import TransportError

def messages(response,stop_event,limit=4*1024*1024):
    data=[]
    total=0
    def lines():
        if hasattr(response,'readline'):
            while not stop_event.is_set():
                line=response.readline(limit+1)
                if not line:return
                yield line
        else:
            yield from response
    for line in lines():
        if stop_event.is_set():return
        total+=len(line)
        if len(line)>limit or total>limit:
            raise TransportError('Живе повідомлення перевищує ліміт клієнта',0,'live.too_large')
        # HTTPResponse may return a partial final line on EOF. It is not a JSON
        # event even when the prefix happens to start with 'data:'.
        if not line.endswith(b'\n'):
            raise TransportError('Живий канал обірвався посеред повідомлення',0,'live.incomplete')
        line=line.rstrip(b'\r\n')
        if not line:
            if data:
                payload=b'\n'.join(data);data=[]
                try:value=json.loads(payload)
                except (ValueError,UnicodeError) as exc:
                    error=TransportError('Некоректне повідомлення живого каналу; виконується перепідключення',0,'live.invalid')
                    error.payload_bytes=len(payload);error.json_position=getattr(exc,'pos',None);raise error from exc
                if not isinstance(value,dict):raise TransportError('Некоректна структура живого повідомлення',0,'live.invalid')
                yield value
            total=0
            continue
        if line.startswith(b'data:'):
            value=line[5:];data.append(value[1:] if value.startswith(b' ') else value)
    if not stop_event.is_set():
        raise TransportError('Живий канал обірвався до завершення події' if data else 'Сервер закрив живий канал',0,'live.incomplete' if data else 'live.closed')
