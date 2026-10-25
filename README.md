# KVault

A **Redis-compatible in-memory data store, written from scratch in pure Python** — zero dependencies, only the standard library.

Talk to it with any standard Redis client (`redis-cli`, `redis-py`, …) — it speaks real **RESP**, the Redis wire protocol.

```bash
git clone https://github.com/deepeshhh1/kvault.git
cd kvault
python -m kvault            # starts on 127.0.0.1:6379
redis-cli PING                 # PONG
redis-cli SET user:1:name Deepesh
redis-cli GET user:1:name      # "Deepesh"
```

## Why this exists

Redis is one of the most-used pieces of infrastructure in the world, and its core ideas — the RESP protocol, an in-memory store, TTLs, persistence — are surprisingly small. KVault rebuilds them from first principles so you can read every line and understand how a real data store works.

## Features

| Area | What's in |
|---|---|
| **Protocol** | Full RESP encoder/decoder; works with `redis-cli` and `redis-py` |
| **Strings** | `SET` (with `EX`/`PX`/`NX`/`XX`), `GET`, `DEL`, `EXISTS`, `INCR`, `DECR`, `INCRBY`, `DECRBY`, `SETEX`, `PSETEX`, `TYPE`, `KEYS` |
| **Expiry** | `EXPIRE`, `TTL` (lazy expiry on access) |
| **Lists** | `LPUSH`, `RPUSH`, `LPOP`, `RPOP`, `LLEN`, `LRANGE` |
| **Hashes** | `HSET`, `HGET`, `HGETALL`, `HDEL`, `HLEN` |
| **Sets** | `SADD`, `SREM`, `SMEMBERS`, `SCARD`, `SISMEMBER` |
| **Server** | Threaded TCP server, `PING`, `ECHO`, `INFO`, `DBSIZE`, `FLUSHALL`, `SAVE`, `SHUTDOWN` |
| **Persistence** | Snapshot (`dump.rdb`) on `SAVE`/shutdown + append-only file (`appendonly.aof`) replayed at startup |

## Architecture

```
kvault/
├── resp.py          # RESP encoding / incremental parsing
├── store.py         # in-memory store: strings, lists, hashes, sets + TTLs
├── commands.py      # one function per command; the dispatcher
├── persistence.py   # RDB-style snapshots + AOF append/replay
└── server.py        # threaded TCP server (one thread per client)
```

One lock guards the store, so concurrent clients stay consistent. Expiry is lazy: a key is removed the first time it is touched after its deadline.

## Quick start

```bash
git clone https://github.com/deepeshhh1/kvault.git
cd kvault
python -m kvault --port 6379 --dir data
```

```bash
# in another terminal — no client library needed:
python examples/demo.py
```

## Tests

```bash
python -m unittest discover tests   # 8 integration tests, real server on a socket
```

## Benchmark

On a laptop, a single client doing `SET`/`GET` in a loop measures roughly **~29,000 ops/sec** (measured 2026-10-25, pure Python, threaded server — real Redis is much faster, in C; the point here is clarity, not speed).

## Roadmap

- [ ] Pub/Sub (`SUBSCRIBE` / `PUBLISH`)
- [ ] Sorted sets (`ZADD`, `ZRANGE`)
- [ ] Transactions (`MULTI` / `EXEC`)
- [ ] Replication (primary → replica)
- [ ] LRU eviction (`maxmemory`)

## License

MIT — see [LICENSE](LICENSE).
