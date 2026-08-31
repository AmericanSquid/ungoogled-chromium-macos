#!/usr/bin/env python3
"""End-to-end socket tests for gzipper_worker.py."""

import importlib.util
import pathlib
import socket
import struct
import threading
import unittest


WORKER_PATH = pathlib.Path(__file__).with_name("gzipper_worker.py")
SPEC = importlib.util.spec_from_file_location("gzipper_worker", WORKER_PATH)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class GzipperWorkerTest(unittest.TestCase):
    def exchange(self, operation, payload, request_id=1):
        server, client = socket.socketpair()
        thread = threading.Thread(target=worker.handle, args=(server, "test"))
        thread.start()
        client.sendall(
            worker.HEADER.pack(
                worker.MAGIC,
                worker.VERSION,
                worker.REQUEST,
                operation,
                request_id,
                len(payload),
            )
            + payload
        )
        response = bytearray()
        while True:
            chunk = client.recv(65536)
            if not chunk:
                break
            response.extend(chunk)
        client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        return worker.HEADER.unpack(response[: worker.HEADER.size]), bytes(
            response[worker.HEADER.size :]
        )

    def test_raw_deflate_and_inflate(self):
        source = b"raw-deflate-data" * 100
        compressed = worker.process(worker.DEFLATE, source)
        header, output = self.exchange(
            worker.INFLATE, struct.pack("!Q", len(source)) + compressed
        )
        self.assertEqual(worker.SUCCESS, header[2])
        self.assertEqual(source, output)

    def test_gzip_compress_and_uncompress(self):
        source = b"gzip-data" * 100
        compressed = worker.process(worker.COMPRESS, source)
        header, output = self.exchange(worker.UNCOMPRESS, compressed)
        self.assertEqual(worker.SUCCESS, header[2])
        self.assertEqual(source, output)

    def test_inflate_limit_returns_failure(self):
        source = b"too-large-for-limit"
        compressed = worker.process(worker.DEFLATE, source)
        header, _ = self.exchange(
            worker.INFLATE, struct.pack("!Q", 1) + compressed
        )
        self.assertEqual(worker.FAILURE, header[2])

    def test_bad_magic_returns_failure(self):
        server, client = socket.socketpair()
        thread = threading.Thread(target=worker.handle, args=(server, "test"))
        thread.start()
        client.sendall(
            worker.HEADER.pack(b"BAD!", worker.VERSION, worker.REQUEST,
                               worker.COMPRESS, 9, 0)
        )
        response = client.recv(65536)
        client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        header = worker.HEADER.unpack(response[: worker.HEADER.size])
        self.assertEqual(worker.FAILURE, header[2])
        self.assertEqual(9, header[4])

    def test_oversized_payload_returns_failure(self):
        server, client = socket.socketpair()
        thread = threading.Thread(target=worker.handle, args=(server, "test"))
        thread.start()
        client.sendall(
            worker.HEADER.pack(worker.MAGIC, worker.VERSION, worker.REQUEST,
                               worker.COMPRESS, 10, worker.MAX_PAYLOAD + 1)
        )
        response = client.recv(65536)
        client.close()
        thread.join(2)
        self.assertFalse(thread.is_alive())
        header = worker.HEADER.unpack(response[: worker.HEADER.size])
        self.assertEqual(worker.FAILURE, header[2])
        self.assertEqual(10, header[4])


if __name__ == "__main__":
    unittest.main()
