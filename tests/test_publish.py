import unittest
from scripts.check_publish import allowed_path, scan_text


class Tests(unittest.TestCase):
    def test_method_files_allowed(self):
        for path in ["README.md", "cloud_export_web.py", "docs/fds.md", "tests/test_fds_tools.py"]:
            self.assertTrue(allowed_path(path))

    def test_data_paths_blocked(self):
        for path in ["private/token.json", "health.sqlite", "capture.har", "route.gpx", "reports/result.md", "../escape.md"]:
            self.assertFalse(allowed_path(path))

    def test_key_names_are_not_values(self):
        self.assertEqual(scan_text("protocol fields: service_token ssecurity sid"), [])

    def test_credential_values_blocked_without_echo(self):
        value = "FAKE" + "-NOT-AN-ALLOWED-FIXTURE"
        result = scan_text('{"service_token": "' + value + '"}')
        self.assertEqual(result, ["literal-credential-value"])
        self.assertNotIn(value, str(result))

    def test_personal_paths_blocked(self):
        self.assertIn("personal-absolute-path", scan_text("/" + "Users/fixture/private"))


if __name__ == "__main__":
    unittest.main()
