"""RESP (Redis Serialization Protocol) encoding and decoding.

RESP is the wire protocol real Redis speaks. Implementing it means any
standard Redis client (redis-cli, redis-py, etc.) can talk to KVault
without modification.
"""

CRLF = b"\r\n"


class RespError(Exception):
    """Raised when a client sends malformed RESP data."""


def encode_simple_string(value: str) -> bytes:
    return b"+" + value.encode() + CRLF


def encode_error(message: str) -> bytes:
    return b"-ERR " + message.encode() + CRLF


def encode_integer(value: int) -> bytes:
    return b":" + str(value).encode() + CRLF


def encode_bulk_string(value):
    """Encode a bulk string; None becomes a null bulk string."""
    if value is None:
        return b"$-1" + CRLF
    if isinstance(value, str):
        value = value.encode()
    return b"$" + str(len(value)).encode() + CRLF + value + CRLF


def encode_array(items) -> bytes:
    """Encode a list; None becomes a null array."""
    if items is None:
        return b"*-1" + CRLF
    out = b"*" + str(len(items)).encode() + CRLF
    for item in items:
        out += encode_bulk_string(item)
    return out


class RespParser:
    """Incremental RESP parser over a buffered socket file object.

    Only the types a client can send are parsed: arrays of bulk strings
    (commands) and inline commands (plain text, for hand-testing).
    """

    def __init__(self, rfile):
        self.rfile = rfile

    def read_command(self):
        """Return the next command as a list of bytes, or None on EOF."""
        line = self.rfile.readline()
        if not line:
            return None
        line = line.strip()
        if not line:
            return self.read_command()
        if line.startswith(b"*"):
            try:
                count = int(line[1:])
            except ValueError:
                raise RespError("invalid array length")
            args = []
            for _ in range(count):
                header = self.rfile.readline()
                if not header.startswith(b"$"):
                    raise RespError("expected bulk string")
                length = int(header[1:].strip())
                if length < 0:
                    args.append(None)
                    continue
                data = self.rfile.read(length + 2)  # payload + CRLF
                args.append(data[:-2])
            return args
        # Inline command: "PING", "SET key value", ...
        return line.split()
