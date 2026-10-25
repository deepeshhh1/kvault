"""Command dispatch: every supported command, one function each.

The dispatcher takes a parsed command (list of bytes) and returns RESP
bytes. ``replay=True`` is used when the AOF is re-applied at startup:
no reply is needed and nothing is re-appended.
"""

import time

from . import resp
from .store import WrongTypeError

WRITE_COMMANDS = {
    b"SET", b"SETEX", b"PSETEX", b"DEL", b"INCR", b"DECR", b"INCRBY",
    b"DECRBY", b"EXPIRE", b"LPUSH", b"RPUSH", b"LPOP", b"RPOP",
    b"HSET", b"HDEL", b"SADD", b"SREM", b"FLUSHALL",
}


def _int_arg(arg, name="value"):
    try:
        return int(arg)
    except (TypeError, ValueError):
        raise ValueError(f"{name} is not an integer")


class Dispatcher:
    def __init__(self, store, persistence, server):
        self.store = store
        self.persistence = persistence
        self.server = server
        self.started_at = time.time()
        self.commands_run = 0

    def dispatch(self, args, replay=False):
        if not args:
            return resp.encode_error("empty command")
        name = args[0].upper()
        handler = getattr(self, "cmd_" + name.decode("ascii", "ignore").lower(), None)
        if handler is None:
            return resp.encode_error(f"unknown command '{name.decode('utf-8', 'replace')}'")
        try:
            result = handler(args[1:])
        except WrongTypeError as e:
            return resp.encode_error(str(e))
        except (ValueError, IndexError) as e:
            return resp.encode_error(f"wrong number of arguments for '{name.decode()}' command"
                                     if isinstance(e, IndexError) else str(e))
        if not replay:
            self.commands_run += 1
            if name in WRITE_COMMANDS:
                self.persistence.append(args)
        return result

    # -- connection / server -----------------------------------------
    def cmd_ping(self, args):
        return resp.encode_simple_string(args[0].decode() if args else "PONG")

    def cmd_echo(self, args):
        return resp.encode_bulk_string(args[0])

    def cmd_info(self, args):
        lines = [
            "# Server",
            "kvault_version:1.0.0",
            f"uptime_in_seconds:{int(time.time() - self.started_at)}",
            f"total_commands_processed:{self.commands_run}",
            "# Keyspace",
            f"db0:keys={len(self.store.data)},expires={len(self.store.expires)}",
        ]
        return resp.encode_bulk_string("\r\n".join(lines))

    def cmd_command(self, args):
        return resp.encode_array([])

    def cmd_dbsize(self, args):
        return resp.encode_integer(len(self.store.data))

    def cmd_flushall(self, args):
        self.store.flush()
        return resp.encode_simple_string("OK")

    def cmd_save(self, args):
        self.persistence.save_snapshot()
        return resp.encode_simple_string("OK")

    def cmd_shutdown(self, args):
        self.persistence.save_snapshot()
        self.server.request_shutdown()
        return resp.encode_simple_string("OK")

    # -- strings -----------------------------------------------------
    def cmd_set(self, args):
        key, value = args[0], args[1]
        expire_at = None
        i = 2
        nx = xx = False
        while i < len(args):
            opt = args[i].upper()
            if opt == b"EX":
                expire_at = time.monotonic() + _int_arg(args[i + 1], "timeout")
                i += 2
            elif opt == b"PX":
                expire_at = time.monotonic() + _int_arg(args[i + 1], "timeout") / 1000
                i += 2
            elif opt == b"NX":
                nx = True
                i += 1
            elif opt == b"XX":
                xx = True
                i += 1
            else:
                raise ValueError("syntax error")
        if nx and self.store.exists(key):
            return resp.encode_bulk_string(None)
        if xx and not self.store.exists(key):
            return resp.encode_bulk_string(None)
        self.store.set(key, value, expire_at)
        return resp.encode_simple_string("OK")

    def cmd_get(self, args):
        return resp.encode_bulk_string(self.store.get(args[0]))

    def cmd_del(self, args):
        return resp.encode_integer(self.store.delete(*args))

    def cmd_exists(self, args):
        return resp.encode_integer(sum(1 for k in args if self.store.exists(k)))

    def cmd_incr(self, args):
        return self._incrby(args[0], 1)

    def cmd_decr(self, args):
        return self._incrby(args[0], -1)

    def cmd_incrby(self, args):
        return self._incrby(args[0], _int_arg(args[1], "increment"))

    def cmd_decrby(self, args):
        return self._incrby(args[0], -_int_arg(args[1], "decrement"))

    def _incrby(self, key, delta):
        current = self.store.get(key)
        value = 0 if current is None else _int_arg(current, "value")
        value += delta
        self.store.set(key, str(value).encode())
        return resp.encode_integer(value)

    def cmd_setex(self, args):
        key, seconds, value = args[0], _int_arg(args[1], "timeout"), args[2]
        self.store.set(key, value, time.monotonic() + seconds)
        return resp.encode_simple_string("OK")

    def cmd_psetex(self, args):
        key, ms, value = args[0], _int_arg(args[1], "timeout"), args[2]
        self.store.set(key, value, time.monotonic() + ms / 1000)
        return resp.encode_simple_string("OK")

    def cmd_expire(self, args):
        return resp.encode_integer(1 if self.store.expire(args[0], _int_arg(args[1], "timeout")) else 0)

    def cmd_ttl(self, args):
        return resp.encode_integer(self.store.ttl(args[0]))

    def cmd_type(self, args):
        key = args[0]
        if not self.store.exists(key):
            return resp.encode_simple_string("none")
        value = self.store.data[key]
        kind = {bytes: "string", list: "list", dict: "hash", set: "set"}[type(value)]
        return resp.encode_simple_string(kind)

    def cmd_keys(self, args):
        return resp.encode_array(self.store.keys(args[0] if args else b"*"))

    # -- lists -------------------------------------------------------
    def _list(self, key, create=False):
        lst = self.store.get_list(key)
        if lst is None and create:
            lst = []
            self.store.put(key, lst)
        return lst

    def cmd_lpush(self, args):
        lst = self._list(args[0], create=True)
        for value in args[1:]:
            lst.insert(0, value)
        return resp.encode_integer(len(lst))

    def cmd_rpush(self, args):
        lst = self._list(args[0], create=True)
        lst.extend(args[1:])
        return resp.encode_integer(len(lst))

    def cmd_lpop(self, args):
        lst = self._list(args[0])
        if not lst:
            return resp.encode_bulk_string(None)
        return resp.encode_bulk_string(lst.pop(0))

    def cmd_rpop(self, args):
        lst = self._list(args[0])
        if not lst:
            return resp.encode_bulk_string(None)
        return resp.encode_bulk_string(lst.pop())

    def cmd_llen(self, args):
        lst = self._list(args[0])
        return resp.encode_integer(0 if lst is None else len(lst))

    def cmd_lrange(self, args):
        lst = self._list(args[0])
        if lst is None:
            return resp.encode_array([])
        start, stop = _int_arg(args[1], "start"), _int_arg(args[2], "stop")
        n = len(lst)
        start = start + n if start < 0 else start
        stop = stop + n if stop < 0 else stop
        start = max(start, 0)
        stop = min(stop, n - 1)
        if start > stop or start >= n:
            return resp.encode_array([])
        return resp.encode_array(lst[start:stop + 1])

    # -- hashes ------------------------------------------------------
    def cmd_hset(self, args):
        h = self.store.get_hash(args[0])
        if h is None:
            h = {}
            self.store.put(args[0], h)
        added = 0
        i = 1
        while i + 1 < len(args) + 1 and i < len(args):
            if args[i] not in h:
                added += 1
            h[args[i]] = args[i + 1]
            i += 2
        return resp.encode_integer(added)

    def cmd_hget(self, args):
        h = self.store.get_hash(args[0])
        return resp.encode_bulk_string(None if h is None else h.get(args[1]))

    def cmd_hgetall(self, args):
        h = self.store.get_hash(args[0])
        if not h:
            return resp.encode_array([])
        flat = []
        for field, value in h.items():
            flat.extend([field, value])
        return resp.encode_array(flat)

    def cmd_hdel(self, args):
        h = self.store.get_hash(args[0])
        if h is None:
            return resp.encode_integer(0)
        removed = sum(1 for f in args[1:] if h.pop(f, None) is not None)
        return resp.encode_integer(removed)

    def cmd_hlen(self, args):
        h = self.store.get_hash(args[0])
        return resp.encode_integer(0 if h is None else len(h))

    # -- sets --------------------------------------------------------
    def cmd_sadd(self, args):
        s = self.store.get_set(args[0])
        if s is None:
            s = set()
            self.store.put(args[0], s)
        before = len(s)
        s.update(args[1:])
        return resp.encode_integer(len(s) - before)

    def cmd_srem(self, args):
        s = self.store.get_set(args[0])
        if s is None:
            return resp.encode_integer(0)
        removed = sum(1 for m in args[1:] if m in s)
        s.difference_update(args[1:])
        return resp.encode_integer(removed)

    def cmd_smembers(self, args):
        s = self.store.get_set(args[0])
        return resp.encode_array([] if s is None else sorted(s))

    def cmd_scard(self, args):
        s = self.store.get_set(args[0])
        return resp.encode_integer(0 if s is None else len(s))

    def cmd_sismember(self, args):
        s = self.store.get_set(args[0])
        return resp.encode_integer(1 if s is not None and args[1] in s else 0)
