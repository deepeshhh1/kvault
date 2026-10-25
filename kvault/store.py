"""The in-memory data store: strings, lists, hashes and sets, with TTLs.

All values are kept as Python objects; keys are bytes. Every mutation is
guarded by one lock, so the threaded server stays consistent.
"""

import threading
import time


class WrongTypeError(Exception):
    pass


class Store:
    def __init__(self):
        self.data = {}       # key (bytes) -> value (bytes | list | dict | set)
        self.expires = {}    # key (bytes) -> deadline (float, monotonic seconds)
        self.lock = threading.RLock()

    # -- expiry ------------------------------------------------------
    def _is_expired(self, key):
        deadline = self.expires.get(key)
        if deadline is not None and time.monotonic() >= deadline:
            self.data.pop(key, None)
            self.expires.pop(key, None)
            return True
        return False

    def exists(self, key):
        with self.lock:
            if self._is_expired(key):
                return False
            return key in self.data

    def get(self, key):
        with self.lock:
            if self._is_expired(key):
                return None
            value = self.data.get(key)
            if value is None:
                return None
            if not isinstance(value, bytes):
                raise WrongTypeError(
                    "WRONGTYPE Operation against a key holding the wrong kind of value")
            return value

    def set(self, key, value, expire_at=None):
        with self.lock:
            self.data[key] = value
            if expire_at is None:
                self.expires.pop(key, None)
            else:
                self.expires[key] = expire_at

    def delete(self, *keys):
        with self.lock:
            removed = 0
            for key in keys:
                self._is_expired(key)
                if key in self.data:
                    del self.data[key]
                    self.expires.pop(key, None)
                    removed += 1
            return removed

    def ttl(self, key):
        """Seconds left: -2 if the key does not exist, -1 if it has no TTL."""
        with self.lock:
            if self._is_expired(key) or key not in self.data:
                return -2
            deadline = self.expires.get(key)
            if deadline is None:
                return -1
            return max(0, int(deadline - time.monotonic()))

    def expire(self, key, seconds):
        with self.lock:
            if self._is_expired(key) or key not in self.data:
                return False
            self.expires[key] = time.monotonic() + seconds
            return True

    def keys(self, pattern=b"*"):
        """Glob-style key listing; only '*' is supported (like KEYS *)."""
        with self.lock:
            for key in list(self.data):
                self._is_expired(key)
            if pattern == b"*":
                return sorted(self.data.keys())
            import fnmatch
            return sorted(k for k in self.data
                          if fnmatch.fnmatchcase(k.decode("utf-8", "replace"),
                                                 pattern.decode("utf-8", "replace")))

    def flush(self):
        with self.lock:
            self.data.clear()
            self.expires.clear()

    # -- typed access ------------------------------------------------
    def _typed(self, key, kind):
        if self._is_expired(key):
            return None
        value = self.data.get(key)
        if value is None:
            return None
        if not isinstance(value, kind):
            raise WrongTypeError(
                "WRONGTYPE Operation against a key holding the wrong kind of value")
        return value

    def get_list(self, key):
        with self.lock:
            return self._typed(key, list)

    def get_hash(self, key):
        with self.lock:
            return self._typed(key, dict)

    def get_set(self, key):
        with self.lock:
            return self._typed(key, set)

    def put(self, key, value):
        with self.lock:
            self.data[key] = value
            self.expires.pop(key, None)
