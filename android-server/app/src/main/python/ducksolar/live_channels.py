"""Own live sockets by account/client; shutdown never clears durable PUSH."""
import socket
import threading


class LiveChannels:
    def __init__(self):
        self.lock = threading.Lock()
        self.channels = {}
        self.stopped = False

    @staticmethod
    def interrupt(channel, reason):
        channel['reason'] = reason
        channel['cancelled'].set();channel['wake'].set()
        try:
            channel['socket'].shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def open(self, account, client_id, connection):
        key = (account, client_id)
        channel = dict(socket=connection, cancelled=threading.Event(), wake=threading.Event(), reason='')
        with self.lock:
            if self.stopped:
                raise ConnectionAbortedError('Server stopping')
            previous = self.channels.get(key)
            self.channels[key] = channel
        if previous is not None:
            self.interrupt(previous, 'replaced')
        return key, channel

    def release(self, key, channel):
        with self.lock:
            if self.channels.get(key) is channel:
                del self.channels[key]

    def stop(self):
        with self.lock:
            self.stopped = True
            channels = list(self.channels.values())
            self.channels.clear()
        for channel in channels:
            self.interrupt(channel, 'server_stopping')
