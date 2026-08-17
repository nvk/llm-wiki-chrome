from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tests" / "chrome" / "run_extension_e2e.py"
SPEC = importlib.util.spec_from_file_location("browser_extension_e2e", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ChromeIntegrationHarnessTests(unittest.TestCase):
    def test_fixed_extension_id_is_derived_from_manifest_key(self) -> None:
        manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
        extension_id = MODULE.extension_id_from_key(manifest["key"])
        self.assertRegex(extension_id, r"^[a-p]{32}$")
        self.assertEqual(extension_id, "ohcoklaeeeacdfjibklhcmhfdamfnkmd")

    def test_target_validation_is_exact_and_origin_bounded(self) -> None:
        accepted = "https://x.com/i/spaces/SYNTHETIC_SPACE?synthetic=1"
        self.assertEqual(MODULE.validate_target_url(accepted), accepted)
        for rejected in (
            "http://x.com/i/spaces/SYNTHETIC_SPACE",
            "https://example.invalid/synthetic",
            "https://user@x.com/synthetic",
            "https://x.com/synthetic#fragment",
        ):
            with self.subTest(rejected=rejected):
                with self.assertRaises(MODULE.IntegrationError):
                    MODULE.validate_target_url(rejected)


if __name__ == "__main__":
    unittest.main()
