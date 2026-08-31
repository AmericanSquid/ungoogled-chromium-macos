#!/usr/bin/env python3
"""NON-PRODUCTION protocol-v1 development harness.

The production worker is Chromium's Linux x86_64 GN target
//content/distributed:distributed_utility_worker. This Python program exists
only for local protocol development and must not be deployed.
"""

import argparse
import hmac
import logging
import socket
import struct
import zlib


MAGIC = b"UCD1"
VERSION = 1
REQUEST_HEADER = struct.Struct("!4sHBBQIQ")
RESPONSE_HEADER = struct.Struct("!4sHBBQIQ")
DEFLATE = 1
SUCCESS = 1
FAILURE = 2
ERROR_NONE = 0
ERROR_MISSING_AUTHENTICATION = 1
ERROR_AUTHENTICATION_FAILED = 2
ERROR_UNSUPPORTED_OPERATION = 3
ERROR_MALFORMED_FRAME = 4
ERROR_OVERSIZED_PAYLOAD = 5
ERROR_INTERNAL = 6
MAX_AUTHENTICATION = 4096
MAX_PAYLOAD = 64 * 1024 * 1024


class ProtocolError(Exception):
    def __init__(self, error_code, request_id=0):
        super().__init__(f"protocol error {error_code}")
        self.error_code = error_code
        self.request_id = request_id


def read_exact(connection, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise ProtocolError(ERROR_MALFORMED_FRAME)
        chunks.extend(chunk)
    return bytes(chunks)


def read_request(connection):
    header = read_exact(connection, REQUEST_HEADER.size)
    magic, version, operation, reserved, request_id, auth_size, payload_size = (
        REQUEST_HEADER.unpack(header)
    )
    if request_id == 0:
        raise ProtocolError(ERROR_MALFORMED_FRAME)
    if magic != MAGIC or version != VERSION or reserved != 0:
        raise ProtocolError(ERROR_MALFORMED_FRAME, request_id)
    if payload_size > MAX_PAYLOAD:
        raise ProtocolError(ERROR_OVERSIZED_PAYLOAD, request_id)
    if auth_size > MAX_AUTHENTICATION:
        raise ProtocolError(ERROR_MALFORMED_FRAME, request_id)
    authentication = read_exact(connection, auth_size)
    payload = read_exact(connection, payload_size)
    return request_id, operation, authentication, payload


def write_response(connection, request_id, status, error, payload=b""):
    if request_id == 0 or len(payload) > MAX_PAYLOAD:
        raise ProtocolError(ERROR_INTERNAL, request_id)
    connection.sendall(
        RESPONSE_HEADER.pack(
            MAGIC, VERSION, status, 0, request_id, error, len(payload)
        )
        + payload
    )


def raw_deflate(data):
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


def handle(connection, expected_token):
    connection.settimeout(10)
    request_id = 0
    try:
        request_id, operation, authentication, payload = read_request(connection)
        if not authentication:
            raise ProtocolError(ERROR_MISSING_AUTHENTICATION, request_id)
        if not hmac.compare_digest(authentication, expected_token):
            raise ProtocolError(ERROR_AUTHENTICATION_FAILED, request_id)
        if operation != DEFLATE:
            raise ProtocolError(ERROR_UNSUPPORTED_OPERATION, request_id)
        write_response(
            connection, request_id, SUCCESS, ERROR_NONE, raw_deflate(payload)
        )
    except ProtocolError as error:
        if error.request_id:
            try:
                write_response(
                    connection, error.request_id, FAILURE, error.error_code
                )
            except OSError:
                pass
    except (OSError, zlib.error):
        if request_id:
            try:
                write_response(connection, request_id, FAILURE, ERROR_INTERNAL)
            except OSError:
                pass
    finally:
        connection.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="NON-PRODUCTION remote Gzipper protocol harness"
    )
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--token-file", required=True)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.host in ("0.0.0.0", "::"):
        raise SystemExit("refusing to bind a wildcard address")
    with open(args.token_file, "rb") as token_stream:
        expected_token = token_stream.read().strip()
    if not expected_token:
        raise SystemExit("token file is empty")

    family = socket.AF_INET6 if ":" in args.host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.host, args.port))
        listener.listen()
        logging.warning(
            "NON-PRODUCTION harness listening on %s:%d", args.host, args.port
        )
        try:
            while True:
                connection, _ = listener.accept()
                handle(connection, expected_token)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    main()
