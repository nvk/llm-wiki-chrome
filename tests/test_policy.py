from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from browser_executor.policy import LocalBrowserPolicy, PolicyError


class LocalBrowserPolicyTests(unittest.TestCase):
    def test_file_roots_are_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            upload = root / "upload"
            download = root / "download"
            outside = root / "outside"
            upload.mkdir()
            download.mkdir()
            outside.mkdir()
            source = upload / "synthetic.txt"
            source.write_text("synthetic", encoding="utf-8")
            result = download / "result.bin"
            result.write_bytes(b"synthetic")
            config = root / "policy.json"
            config.write_text(
                json.dumps(
                    {
                        "upload_roots": [str(upload)],
                        "download_roots": [str(download)],
                    }
                ),
                encoding="utf-8",
            )
            policy = LocalBrowserPolicy.load(config)
            self.assertEqual(policy.validate_uploads([str(source)]), [source.resolve()])
            self.assertEqual(policy.validate_download(str(result)), result.resolve())
            forbidden = outside / "private.txt"
            forbidden.write_text("private", encoding="utf-8")
            with self.assertRaisesRegex(PolicyError, "outside"):
                policy.validate_uploads([str(forbidden)])

    def test_absent_policy_grants_no_file_access(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            policy = LocalBrowserPolicy.load(Path(directory) / "missing.json")
            with self.assertRaisesRegex(PolicyError, "no upload roots"):
                policy.validate_uploads([str(Path(directory) / "missing")])


if __name__ == "__main__":
    unittest.main()
