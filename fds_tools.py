#!/usr/bin/env python3
"""Offline FDS helpers. No account login, network calls, or bundled real data."""
from __future__ import annotations
import argparse, base64, hashlib, json, math, os, struct, sys
from pathlib import Path

IV = b"1234567887654321"  # Protocol constant, NOT an account credential.


def b64decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def make_suffix(sid: str, timestamp: int, timezone_quarters: int,
                proto_type: int, file_type: int) -> str:
    """Use the exact sport record SID, not a guessed hardware device ID."""
    if not isinstance(sid, str) or not sid:
        raise ValueError("SID_REQUIRED")
    if not isinstance(timestamp, int) or isinstance(timestamp, bool) or not 0 <= timestamp < 2**32:
        raise ValueError("INVALID_TIMESTAMP")
    if not isinstance(timezone_quarters, int) or not -128 <= timezone_quarters <= 255:
        raise ValueError("TIMEZONE_REQUIRES_QUARTER_HOURS_NOT_SECONDS")
    if not isinstance(proto_type, int) or not 0 <= proto_type < 32 or file_type not in range(4):
        raise ValueError("UNSUPPORTED_PROTO_OR_FILE_TYPE")
    tag = (128 + (proto_type << 2) + file_type) & 255
    packed = struct.pack("<I", timestamp) + bytes((timezone_quarters & 255, tag))
    enc = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
    return enc(packed) + "_" + enc(hashlib.sha1(sid.encode()).digest())


def aes_cbc_decrypt(ciphertext: bytes, key: bytes, iv: bytes = IV,
                    padding: bool = True) -> bytes:
    if len(key) not in (16, 24, 32) or len(iv) != 16 or not ciphertext or len(ciphertext) % 16:
        raise ValueError("INVALID_AES_LENGTH")
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    plain = decryptor.update(ciphertext) + decryptor.finalize()
    if padding:
        unpadder = PKCS7(128).unpadder()
        plain = unpadder.update(plain) + unpadder.finalize()
    return plain


def decrypt_fds(blob: bytes, object_key: str) -> bytes:
    try:
        text = json.loads(blob)
    except ValueError:
        text = blob.decode("ascii").strip()
    if not isinstance(text, str):
        raise ValueError("FDS_EXPECTED_BASE64_STRING")
    return aes_cbc_decrypt(b64decode(text), b64decode(object_key))


def decode_gps(blob: bytes) -> dict:
    if len(blob) < 9:
        raise ValueError("GPS_HEADER_TRUNCATED")
    timestamp = struct.unpack_from("<I", blob)[0]
    version, proto_type, validity = blob[5], blob[6], blob[8]
    if version not in (1, 2, 3, 4):
        raise ValueError("UNSUPPORTED_GPS_VERSION")
    # gps_source has its own validity bit but shares the packed speed uint16.
    specification = [("timestamp", "I", 1), ("longitude", "f", 1),
                     ("latitude", "f", 1), ("accuracy", "f", 2),
                     ("speed_packed", "H", 2), ("gps_source", "", 2),
                     ("altitude", "f", 3), ("hdop", "f", 3)]
    active = [s for s in specification if s[2] <= version]
    valid = {name: bool(validity & (1 << (7 - i))) for i, (name, _, _) in enumerate(active)}
    if not all(valid[name] for name in ("timestamp", "longitude", "latitude")):
        raise ValueError("GPS_REQUIRED_FIELDS_UNAVAILABLE")
    fmt = "<" + "".join(code for _, code, _ in active)
    stride = struct.calcsize(fmt)
    offset = 13 if version >= 4 else 9
    if len(blob) < offset:
        raise ValueError("GPS_COUNT_TRUNCATED")
    size = len(blob) - offset
    if size % stride:
        raise ValueError("GPS_TRAILING_BYTES")
    count = struct.unpack_from("<I", blob, 9)[0] if version >= 4 else size // stride
    if count != size // stride or count > 1_000_000:
        raise ValueError("GPS_COUNT_SIZE_MISMATCH")
    stored = [name for name, code, _ in active if code]
    points = []
    for i in range(count):
        raw = dict(zip(stored, struct.unpack_from(fmt, blob, offset + i * stride)))
        point = {name: value for name, value in raw.items() if valid[name]}
        if any(isinstance(x, float) and not math.isfinite(x) for x in point.values()):
            raise ValueError("GPS_NONFINITE_FIELD")
        if "speed_packed" in point:
            packed = point.pop("speed_packed")
            point["speed_raw_decoded"] = ((packed & 0xFFF0) >> 4) / 10
        if valid.get("gps_source"):
            point["gps_source"] = raw["speed_packed"] & 15
        lat, lon = point["latitude"], point["longitude"]
        if not math.isfinite(lat) or not math.isfinite(lon) or not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat, lon) == (0, 0):
            raise ValueError("GPS_INVALID_COORDINATE")
        point["index"] = i
        points.append(point)
    return {"header_timestamp": timestamp, "timezone_quarters_raw": blob[4],
            "gps_version": version, "proto_type": proto_type, "record_stride": stride,
            "coordinate_reference": "unconfirmed original coordinates; not transformed",
            "time_order_non_decreasing": all(a["timestamp"] <= b["timestamp"] for a, b in zip(points, points[1:])),
            "points": points}


def private_write(path: Path, blob: bytes):
    from cloud_export_web import ensure_private
    ensure_private(path.parent)
    # Do not follow an existing file or silently overwrite an earlier export.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(blob)
        f.flush()
        os.fsync(f.fileno())


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    suffix = sub.add_parser("suffix")
    suffix.add_argument("--record", type=Path, required=True)
    suffix.add_argument("--file-type", type=int, choices=range(4), required=True)
    suffix.add_argument("--out", type=Path, required=True)
    decrypt = sub.add_parser("decrypt")
    decrypt.add_argument("input", type=Path)
    decrypt.add_argument("--key-file", type=Path, required=True)
    decrypt.add_argument("--out", type=Path, required=True)
    gps = sub.add_parser("decode-gps")
    gps.add_argument("input", type=Path)
    gps.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "suffix":
            raw = json.loads(args.record.read_text())
            value = raw["value"]
            value = json.loads(value) if isinstance(value, str) else value
            timestamp = value.get("time")
            if timestamp is None:
                timestamp = value["start_time"]
            result = {"timestamp": timestamp, "suffix": make_suffix(raw["sid"], timestamp,
                      value["timezone"], value["proto_type"], args.file_type)}
            private_write(args.out, (json.dumps(result) + "\n").encode())
        elif args.command == "decrypt":
            if args.key_file.is_symlink() or not args.key_file.is_file() or args.key_file.stat().st_mode & 0o077:
                raise ValueError("KEY_FILE_REQUIRES_PRIVATE_REGULAR_FILE")
            key = json.loads(args.key_file.read_text())["obj_key"]
            private_write(args.out, decrypt_fds(args.input.read_bytes(), key))
        else:
            result = decode_gps(args.input.read_bytes())
            private_write(args.out, (json.dumps(result, ensure_ascii=False) + "\n").encode())
        print("OFFLINE_OUTPUT_SAVED")
        return 0
    except Exception as exc:
        # Do not print exceptions containing user paths, data or secret values.
        print("ERROR " + type(exc).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
