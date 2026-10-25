"""Demo: talk to a running KVault with a raw socket (no dependencies).

Start the server first:  python -m kvault
Then run:               python examples/demo.py
"""

import socket


def send(sock, *args):
    out = f"*{len(args)}\r\n".encode()
    for a in args:
        a = a.encode()
        out += f"${len(a)}\r\n".encode() + a + b"\r\n"
    sock.sendall(out)
    print(sock.recv(4096).decode().strip().replace("\r\n", " | "))


with socket.create_connection(("127.0.0.1", 6379)) as sock:
    send(sock, "PING")
    send(sock, "SET", "user:1:name", "Deepesh")
    send(sock, "GET", "user:1:name")
    send(sock, "INCR", "visits")
    send(sock, "RPUSH", "queue", "job-a", "job-b")
    send(sock, "LRANGE", "queue", "0", "-1")
    send(sock, "HSET", "user:1", "city", "Mandi", "role", "EE student")
    send(sock, "HGETALL", "user:1")
