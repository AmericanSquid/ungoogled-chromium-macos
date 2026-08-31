#!/usr/bin/env python3
"""Tailscale-bound worker for content/distributed/REMOTE_GZIPPER_PROTOCOL.md."""

import argparse
import logging
import socket
import struct
import zlib


MAGIC = b"UCD1"
VERSION = 1
HEADER = struct.Struct("!4sHBBQQ")
REQUEST = 1
SUCCESS = 2
FAILURE = 3
DEFLATE = 1
INFLATE = 2
COMPRESS = 3
UNCOMPRESS = 4
MAX_PAYLOAD = 64 * 1024 * 1024
ERROR_LIMIT = 1024


class ProtocolError(Exception):
    def __init__(self, message, request_id=0, operation=0):
        super().__init__(message)
        self.request_id = request_id
        self.operation = operation


def read_exact(connection, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = connection.recv(size - len(chunks))
        if not chunk:
            raise ProtocolError("unexpected end of connection")
        chunks.extend(chunk)
    return bytes(chunks)


def read_frame(connection):
    magic, version, message_type, operation, request_id, payload_size = (
        HEADER.unpack(read_exact(connection, HEADER.size))
    )
    if magic != MAGIC:
        raise ProtocolError("invalid magic", request_id, operation)
    if version != VERSION:
        raise ProtocolError("unsupported protocol version", request_id, operation)
    if message_type != REQUEST:
        raise ProtocolError("expected a request frame", request_id, operation)
    if operation not in (DEFLATE, INFLATE, COMPRESS, UNCOMPRESS):
        raise ProtocolError("unsupported operation", request_id, operation)
    if request_id == 0:
        raise ProtocolError("request ID must be nonzero", request_id, operation)
    if payload_size > MAX_PAYLOAD:
        raise ProtocolError("payload exceeds 64 MiB limit", request_id, operation)
    return operation, request_id, read_exact(connection, payload_size)


def write_frame(connection, message_type, operation, request_id, payload):
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError("response exceeds 64 MiB limit")
    connection.sendall(
        HEADER.pack(MAGIC, VERSION, message_type, operation, request_id, len(payload))
        + payload
    )


def raw_deflate(data):
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    return compressor.compress(data) + compressor.flush()


def raw_inflate(data, max_size):
    if max_size > MAX_PAYLOAD:
        raise ProtocolError("requested output limit exceeds 64 MiB")
    decompressor = zlib.decompressobj(wbits=-zlib.MAX_WBITS)
    result = decompressor.decompress(data, max_size + 1)
    if len(result) > max_size or decompressor.unconsumed_tail:
        raise ProtocolError("inflated data exceeds requested output limit")
    result += decompressor.flush(max_size + 1 - len(result))
    if len(result) > max_size or not decompressor.eof:
        raise ProtocolError("invalid or incomplete raw DEFLATE payload")
    return result


def gzip_uncompress(data):
    decompressor = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    result = decompressor.decompress(data, MAX_PAYLOAD + 1)
    if len(result) > MAX_PAYLOAD or decompressor.unconsumed_tail:
        raise ProtocolError("gzip output exceeds 64 MiB limit")
    result += decompressor.flush(MAX_PAYLOAD + 1 - len(result))
    if len(result) > MAX_PAYLOAD or not decompressor.eof:
        raise ProtocolError("invalid or incomplete gzip payload")
    return result


def process(operation, payload):
    if operation == DEFLATE:
        return raw_deflate(payload)
    if operation == INFLATE:
        if len(payload) < 8:
            raise ProtocolError("inflate payload is missing its output limit")
        max_size = struct.unpack("!Q", payload[:8])[0]
        return raw_inflate(payload[8:], max_size)
    if operation == COMPRESS:
        compressor = zlib.compressobj(wbits=16 + zlib.MAX_WBITS)
        return compressor.compress(payload) + compressor.flush()
    return gzip_uncompress(payload)


def handle(connection, peer):
    connection.settimeout(10)
    request_id = 0
    operation = 0
    try:
        operation, request_id, payload = read_frame(connection)
        output = process(operation, payload)
        write_frame(connection, SUCCESS, operation, request_id, output)
    except (OSError, ProtocolError, zlib.error) as error:
        logging.warning("request from %s failed: %s", peer, error)
        request_id = request_id or getattr(error, "request_id", 0)
        operation = operation or getattr(error, "operation", 0)
        if request_id:
            message = str(error).encode("utf-8")[:ERROR_LIMIT]
            try:
                write_frame(connection, FAILURE, operation, request_id, message)
            except OSError:
                pass
    finally:
        connection.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Remote Chromium Gzipper worker")
    parser.add_argument(
        "--host",
        required=True,
        help="Tailscale IP address to bind; do not use 0.0.0.0 or ::",
    )
    parser.add_argument("--port", type=int, default=8765)
    return parser.parse_args()


def main():
    args = parse_args()
    if args.host in ("0.0.0.0", "::"):
        raise SystemExit("refusing to bind a public/wildcard address")
    family = socket.AF_INET6 if ":" in args.host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((args.host, args.port))
        listener.listen()
        logging.info("listening on %s:%d", args.host, args.port)
        while True:
            connection, peer = listener.accept()
            handle(connection, peer)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
