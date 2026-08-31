# Debian remote Gzipper worker

This is the Debian side of the experimental remote Data Decoder path. It speaks
the protocol defined in
`content/distributed/REMOTE_GZIPPER_PROTOCOL.md` after Chromium's patch is
applied.

## Run it

Install Python 3.11 or later, copy this directory to the Debian computer, and
bind the worker to that machine's Tailscale IPv4 or IPv6 address:

```sh
python3 gzipper_worker.py --host 100.x.y.z --port 8765
```

Do not use `0.0.0.0`, `::`, a LAN address, or a public address. The worker
refuses wildcard addresses but cannot determine whether another address is
Tailscale-managed, so verify the address yourself with `tailscale ip`.

When the Chromium proxy is implemented, start Chromium with:

```sh
--distributed-data-decoder --distributed-worker=100.x.y.z:8765
```

This service is intentionally single-request and synchronous for the first
experiment. It supports raw-DEFLATE operations separately from gzip operations,
applies the protocol's 64 MiB cap, and closes every connection after responding.

## Test it

Run the worker's socket-level tests on Debian or macOS:

```sh
python3 -m unittest -v test_gzipper_worker.py
```
