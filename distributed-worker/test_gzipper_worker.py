#!/usr/bin/env python3
"""Socket tests for the NON-PRODUCTION Python protocol harness."""

import importlib.util
import pathlib
import socket
import threading
import unittest
import zlib


WORKER_PATH = pathlib.Path(__file__).with_name("gzipper_worker.py")
SPEC = importlib.util.spec_from_file_location("gzipper_worker", WORKER_PATH)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class GzipperDevelopmentHarnessTest(unittest.TestCase):
    def exchange(self, frame, token=b"test-token"):
        client, server = socket.socketpair()
        thread = threading.Thread(target=worker.handle, args=(server, token))
        thread.start()
        client.sendall(frame)
        header = worker.read_exact(client, worker.RESPONSE_HEADER.size)
        fields = worker.RESPONSE_HEADER.unpack(header)
        payload = worker.read_exact(client, fields[-1])
        client.close()
        thread.join(timeout=2)
        self.assertFalse(thread.is_alive())
        return fields, payload

    def request(
        self,
        request_id=7,
        operation=worker.DEFLATE,
        authentication=b"test-token",
        payload=b"payload",
    ):
        return worker.REQUEST_HEADER.pack(
            worker.MAGIC,
            worker.VERSION,
            operation,
            0,
            request_id,
            len(authentication),
            len(payload),
        ) + authentication + payload

    def test_authenticated_deflate_preserves_request_id(self):
        fields, compressed = self.exchange(self.request(request_id=101))
        self.assertEqual(101, fields[4])
        self.assertEqual(worker.SUCCESS, fields[2])
        self.assertEqual(worker.ERROR_NONE, fields[5])
        self.assertEqual(b"payload", zlib.decompress(compressed, wbits=-15))

    def test_missing_token(self):
        fields, payload = self.exchange(self.request(authentication=b""))
        self.assertEqual(worker.FAILURE, fields[2])
        self.assertEqual(worker.ERROR_MISSING_AUTHENTICATION, fields[5])
        self.assertEqual(b"", payload)

    def test_bad_token(self):
        fields, _ = self.exchange(self.request(authentication=b"bad-token"))
        self.assertEqual(worker.ERROR_AUTHENTICATION_FAILED, fields[5])

    def test_unsupported_operation(self):
        fields, _ = self.exchange(self.request(operation=99))
        self.assertEqual(worker.ERROR_UNSUPPORTED_OPERATION, fields[5])

    def test_oversized_payload_is_rejected_from_header(self):
        frame = worker.REQUEST_HEADER.pack(
            worker.MAGIC,
            worker.VERSION,
            worker.DEFLATE,
            0,
            202,
            len(b"test-token"),
            worker.MAX_PAYLOAD + 1,
        )
        fields, _ = self.exchange(frame)
        self.assertEqual(202, fields[4])
        self.assertEqual(worker.ERROR_OVERSIZED_PAYLOAD, fields[5])


if __name__ == "__main__":
    unittest.main()
