# Python development harness (non-production)

This directory is **not the distributed worker shipped with this fork**. The
production implementation is Chromium's Linux x86_64 GN executable:
`//content/distributed:distributed_utility_worker`. Its source, tests, build
instructions, and protocol documentation are added by
`patches/ungoogled-chromium/macos/distributed-utility-proxy.patch`.

The Python program here exists only for quick protocol-v1 experiments. It is
Deflate-only and protocol-compatible, but it does not use Chromium's Gzipper,
Chromium networking, or Chromium's production build and test targets. Do not
deploy it.

For local development only:

```sh
python3 gzipper_worker.py \
  --host=127.0.0.1 \
  --port=8765 \
  --token-file=/path/to/development-token
python3 -m unittest -v test_gzipper_worker.py
```

Neither the token nor request/response payloads are logged.
