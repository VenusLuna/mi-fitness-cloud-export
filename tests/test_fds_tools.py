"""Generated toy records and public NIST vectors only; never real health/GPS."""
import base64, json, struct, unittest
import fds_tools as f


class Tests(unittest.TestCase):
    def test_suffix_structure(self):
        result = f.make_suffix("SYNTHETIC_RECORD", 1700000000, 32, 22, 2)
        self.assertEqual(f.b64decode(result[:8]), struct.pack("<I", 1700000000) + bytes((32, 218)))
        self.assertEqual(len(f.b64decode(result[9:])), 20)

    def test_timezone_seconds_rejected(self):
        with self.assertRaises(ValueError):
            f.make_suffix("SYNTHETIC_RECORD", 1700000000, 28800, 22, 2)

    def test_gps_v2_generated(self):
        header = struct.pack("<I", 1700000000) + bytes((32, 2, 22, 0, 0xFC))
        raw = header + struct.pack("<IfffH", 1700000001, 0.5, 0.5, 2.0, 0x0123)
        result = f.decode_gps(raw)
        self.assertEqual(result["record_stride"], 18)
        self.assertEqual(len(result["points"]), 1)
        self.assertEqual(result["points"][0]["gps_source"], 3)

    def test_gps_v4_empty(self):
        raw = struct.pack("<I", 1700000000) + bytes((32, 4, 22, 0, 0xFF)) + struct.pack("<I", 0)
        self.assertEqual(f.decode_gps(raw)["points"], [])

    def test_reject_unsupported_and_truncated(self):
        for data in [b"", b"123", struct.pack("<I", 1700000000) + bytes((32, 99, 22, 0, 0xFF))]:
            with self.assertRaises(ValueError):
                f.decode_gps(data)

    def test_aes_nist(self):
        try:
            import cryptography
        except ImportError:
            self.skipTest("optional cryptography dependency not installed")
        self.assertEqual(f.aes_cbc_decrypt(bytes.fromhex("7649abac8119b246cee98e9b12e9197d"),
                         bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c"),
                         bytes.fromhex("000102030405060708090a0b0c0d0e0f"), False),
                         bytes.fromhex("6bc1bee22e409f96e93d7e117393172a"))

    def test_aes_padding_roundtrip(self):
        try:
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
            from cryptography.hazmat.primitives.padding import PKCS7
        except ImportError:
            self.skipTest("optional cryptography dependency not installed")
        key = bytes(range(16))
        pad = PKCS7(128).padder()
        raw = pad.update(b"SYNTHETIC_PAYLOAD") + pad.finalize()
        enc = Cipher(algorithms.AES(key), modes.CBC(f.IV)).encryptor()
        encrypted = enc.update(raw) + enc.finalize()
        body = json.dumps(base64.urlsafe_b64encode(encrypted).decode()).encode()
        self.assertEqual(f.decrypt_fds(body, base64.urlsafe_b64encode(key).decode()), b"SYNTHETIC_PAYLOAD")


if __name__ == "__main__":
    unittest.main()
