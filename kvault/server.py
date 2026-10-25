"""Threaded TCP server speaking RESP.

Each client connection runs on its own thread; all commands funnel
through one Dispatcher, and the Store serialises mutations with a lock.
On startup the snapshot is loaded, then the AOF is replayed.
"""

import socket
import socketserver
import threading

from . import resp
from .commands import Dispatcher
from .persistence import Persistence
from .store import Store


class KVaultServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, data_dir="data", aof=True):
        super().__init__(address, _ClientHandler)
        self.store = Store()
        self.persistence = Persistence(data_dir, self.store, aof_enabled=aof)
        self.dispatcher = Dispatcher(self.store, self.persistence, self)
        self._shutdown_requested = threading.Event()
        self.persistence.load_snapshot()
        replayed = self.persistence.replay_aof(self.dispatcher.dispatch)
        self.replayed_aof_commands = replayed

    def request_shutdown(self):
        self._shutdown_requested.set()
        threading.Thread(target=self.shutdown, daemon=True).start()


class _ClientHandler(socketserver.StreamRequestHandler):
    def handle(self):
        parser = resp.RespParser(self.rfile)
        server = self.server
        while True:
            try:
                args = parser.read_command()
            except resp.RespError as e:
                self.wfile.write(resp.encode_error(str(e)))
                self.wfile.flush()
                continue
            except (ConnectionError, OSError):
                return
            if args is None:
                return
            try:
                reply = server.dispatcher.dispatch(args)
            except Exception as e:  # never kill a client on a bad command
                reply = resp.encode_error(f"internal error: {e}")
            try:
                self.wfile.write(reply)
                self.wfile.flush()
            except (ConnectionError, OSError):
                return


def serve(host="127.0.0.1", port=6379, data_dir="data", aof=True):
    """Start the server in the foreground. Returns the server object."""
    server = KVaultServer((host, port), data_dir=data_dir, aof=aof)
    print(f"KVault 1.0.0 listening on {host}:{port} "
          f"(snapshot: {server.persistence.snapshot_path}, "
          f"AOF replayed: {server.replayed_aof_commands} commands)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down, saving snapshot...")
        server.persistence.save_snapshot()
        server.shutdown()
    return server
