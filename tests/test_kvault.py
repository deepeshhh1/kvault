"""Integration tests: a real KVault server on a local socket,
driven with raw RESP by a tiny test client. Run with:
    python -m pytest tests/        (or: python -m unittest discover tests)
"""

import socket
import tempfile
import threading
import unittest

from kvault.server import KVaultServer


def _encode(*args):
    out = f"*{len(args)}\r\n".encode()
    for a in args:
        a = a.encode() if isinstance(a, str) else a
        out += f"${len(a)}\r\n".encode() + a + b"\r\n"
    return out


class Client:
    def __init__(self, port):
        self.sock = socket.create_connection(("127.0.0.1", port))
        self.buf = b""

    def cmd(self, *args):
        self.sock.sendall(_encode(*args))
        return self._read()

    def _read(self):
        while b"\r\n" not in self.buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("server closed the connection")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\r\n", 1)
        kind, rest = line[:1], line[1:]
        if kind == b"+":
            return rest.decode()
        if kind == b"-":
            raise AssertionError(rest.decode())
        if kind == b":":
            return int(rest)
        if kind == b"$":
            n = int(rest)
            if n == -1:
                return None
            while len(self.buf) < n + 2:
                self.buf += self.sock.recv(4096)
            data, self.buf = self.buf[:n], self.buf[n + 2:]
            return data.decode()
        if kind == b"*":
            return [self._read() for _ in range(int(rest))]
        raise AssertionError(f"unexpected reply: {line!r}")

    def close(self):
        self.sock.close()


class KVaultTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.server = KVaultServer(("127.0.0.1", 0), data_dir=cls.tmp.name, aof=False)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        self.c = Client(self.port)
        self.c.cmd("FLUSHALL")

    def tearDown(self):
        self.c.close()

    def test_ping(self):
        self.assertEqual(self.c.cmd("PING"), "PONG")
        self.assertEqual(self.c.cmd("PING", "hello"), "hello")

    def test_strings(self):
        self.assertEqual(self.c.cmd("SET", "k", "v"), "OK")
        self.assertEqual(self.c.cmd("GET", "k"), "v")
        self.assertIsNone(self.c.cmd("GET", "missing"))
        self.assertEqual(self.c.cmd("SET", "k", "v2", "NX"), None)
        self.assertEqual(self.c.cmd("SET", "new", "x", "NX"), "OK")

    def test_counters(self):
        self.assertEqual(self.c.cmd("INCR", "n"), 1)
        self.assertEqual(self.c.cmd("INCR", "n"), 2)
        self.assertEqual(self.c.cmd("INCRBY", "n", "10"), 12)
        self.assertEqual(self.c.cmd("DECR", "n"), 11)

    def test_expiry(self):
        self.c.cmd("SET", "temp", "x", "EX", "100")
        self.assertIn(self.c.cmd("TTL", "temp"), (99, 100))  # a fraction of a second may elapse
        self.c.cmd("SETEX", "t2", "100", "y")
        self.assertEqual(self.c.cmd("GET", "t2"), "y")
        self.assertEqual(self.c.cmd("TTL", "nope"), -2)

    def test_lists(self):
        self.assertEqual(self.c.cmd("RPUSH", "l", "a", "b", "c"), 3)
        self.assertEqual(self.c.cmd("LPUSH", "l", "z"), 4)
        self.assertEqual(self.c.cmd("LRANGE", "l", "0", "-1"), ["z", "a", "b", "c"])
        self.assertEqual(self.c.cmd("LPOP", "l"), "z")
        self.assertEqual(self.c.cmd("LLEN", "l"), 3)

    def test_hashes(self):
        self.assertEqual(self.c.cmd("HSET", "h", "f1", "v1", "f2", "v2"), 2)
        self.assertEqual(self.c.cmd("HGET", "h", "f1"), "v1")
        self.assertEqual(self.c.cmd("HLEN", "h"), 2)
        self.assertEqual(self.c.cmd("HGETALL", "h"), ["f1", "v1", "f2", "v2"])

    def test_sets(self):
        self.assertEqual(self.c.cmd("SADD", "s", "a", "b"), 2)
        self.assertEqual(self.c.cmd("SADD", "s", "a"), 0)
        self.assertEqual(self.c.cmd("SISMEMBER", "s", "a"), 1)
        self.assertEqual(self.c.cmd("SMEMBERS", "s"), ["a", "b"])
        self.assertEqual(self.c.cmd("SCARD", "s"), 2)

    def test_keys_and_type(self):
        self.c.cmd("SET", "a", "1")
        self.c.cmd("RPUSH", "b", "x")
        self.assertEqual(self.c.cmd("KEYS", "*"), ["a", "b"])
        self.assertEqual(self.c.cmd("TYPE", "a"), "string")
        self.assertEqual(self.c.cmd("TYPE", "b"), "list")
        self.assertEqual(self.c.cmd("DBSIZE"), 2)


if __name__ == "__main__":
    unittest.main()
