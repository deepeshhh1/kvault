"""Persistence: snapshots (RDB-style) and an append-only file (AOF).

* Snapshot: the whole store is pickled to ``dump.rdb`` on SAVE/BGSAVE
  and loaded back at startup, so data survives a restart.
* AOF: every write command is appended in RESP form to ``appendonly.aof``
  and replayed at startup (after the snapshot, if both exist).
"""

import os
import pickle
import threading
import time

from . import resp


class Persistence:
    def __init__(self, directory, store, aof_enabled=True):
        self.directory = directory
        self.store = store
        self.aof_enabled = aof_enabled
        self.snapshot_path = os.path.join(directory, "dump.rdb")
        self.aof_path = os.path.join(directory, "appendonly.aof")
        self._aof_lock = threading.Lock()
        os.makedirs(directory, exist_ok=True)

    # -- snapshots ---------------------------------------------------
    def save_snapshot(self):
        tmp = self.snapshot_path + ".tmp"
        with self.store.lock:
            payload = {
                "data": self.store.data,
                "expires": {k: v - time.monotonic() for k, v in self.store.expires.items()},
            }
        with open(tmp, "wb") as f:
            pickle.dump(payload, f)
        os.replace(tmp, self.snapshot_path)
        return True

    def load_snapshot(self):
        if not os.path.exists(self.snapshot_path):
            return False
        with open(self.snapshot_path, "rb") as f:
            payload = pickle.load(f)
        now = time.monotonic()
        with self.store.lock:
            self.store.data = payload["data"]
            self.store.expires = {k: now + ttl for k, ttl in payload["expires"].items()
                                  if ttl > 0}
        return True

    # -- AOF ---------------------------------------------------------
    def append(self, command_args):
        """Append one write command (list of bytes) to the AOF."""
        if not self.aof_enabled:
            return
        with self._aof_lock:
            with open(self.aof_path, "ab") as f:
                f.write(resp.encode_array(command_args))

    def replay_aof(self, dispatch):
        """Replay the AOF through the command dispatcher. Returns count."""
        if not os.path.exists(self.aof_path):
            return 0
        count = 0
        with open(self.aof_path, "rb") as f:
            parser = resp.RespParser(f)
            while True:
                try:
                    args = parser.read_command()
                except Exception:
                    break
                if args is None:
                    break
                dispatch(args, replay=True)
                count += 1
        return count
