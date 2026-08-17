from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AdapterAndSecurityTests(unittest.TestCase):
    def test_manifest_is_private_route_free_and_content_free(self) -> None:
        manifest = json.loads((ROOT / ".llm-wiki-adapter.json").read_text(encoding="utf-8"))
        extension = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["distribution"], "private")
        self.assertEqual(manifest["routes"], [])
        self.assertFalse(manifest["writes_wiki"])
        self.assertEqual(manifest["network"], "none")
        self.assertEqual(manifest["version"], extension["version"])
        self.assertNotIn("content_scripts", extension)
        self.assertEqual(extension["background"]["type"], "module")
        self.assertNotIn("<all_urls>", extension["host_permissions"])
        self.assertEqual(set(extension["host_permissions"]), {
            "https://docs.google.com/*",
            "https://x.com/*",
        })

    def test_service_worker_has_no_arbitrary_execution_or_provider_ui_logic(self) -> None:
        source = "\n".join(
            (ROOT / "extension" / name).read_text(encoding="utf-8")
            for name in ("service-worker.js", "protocol.mjs", "executor.mjs")
        )
        forbidden = (
            "Runtime.evaluate",
            "eval(",
            "new Function",
            "Find and replace",
            "Suggesting",
            "attendee-list",
            "docs-mode-switcher",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, source)
        self.assertIn("new BrowserExecutor", source)
        self.assertIn('"Network.enable"', source)
        self.assertIn('"Network.disable"', source)
        self.assertIn('"Runtime.enable"', source)
        self.assertIn('"Runtime.disable"', source)
        self.assertIn('"Runtime.consoleAPICalled"', source)
        for diagnostic_method in (
            "Network.getResponseBody",
            "Network.getRequestPostData",
            "Network.setRequestInterception",
            "Network.setExtraHTTPHeaders",
            "Fetch.enable",
            "Runtime.getProperties",
            "Runtime.callFunctionOn",
            "Runtime.compileScript",
            "Runtime.runScript",
            "Runtime.awaitPromise",
        ):
            with self.subTest(diagnostic_method=diagnostic_method):
                self.assertNotIn(diagnostic_method, source)
        self.assertIn('error: "invalid-program"', source)
        self.assertNotIn("typed-execution-disabled", source)

    @unittest.skipUnless(shutil.which("node"), "Node is required for the MV3 contract check")
    def test_service_worker_independently_validates_signed_programs(self) -> None:
        harness = r'''
import fs from "node:fs";
import {validateProgram} from "./extension/protocol.mjs";
const program = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
validateProgram(program).then(() => {
  process.stdout.write("ok\n");
}).catch((error) => {
  process.stderr.write(String(error.message || error) + "\n");
  process.exitCode = 2;
});
'''
        for name in ("google-docs-suggestions-v1.json", "x-space-read-v1.json"):
            program_path = ROOT / "tests" / "fixtures" / name
            with self.subTest(name=name):
                completed = subprocess.run(
                    ["node", "--input-type=module", "-e", harness, str(program_path)],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(completed.stdout, "ok\n")

    def test_side_panel_is_status_only(self) -> None:
        html = (ROOT / "extension" / "sidepanel.html").read_text(encoding="utf-8")
        script = (ROOT / "extension" / "sidepanel.js").read_text(encoding="utf-8")
        self.assertNotIn("textarea", html.lower())
        self.assertNotIn("innerHTML", script)
        self.assertIn("never displays page or job content", html)

    def test_describe_matches_manifest(self) -> None:
        manifest = json.loads((ROOT / ".llm-wiki-adapter.json").read_text(encoding="utf-8"))
        completed = subprocess.run(
            [sys.executable, "adapter.py", "describe"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        described = json.loads(completed.stdout)
        self.assertEqual(described["id"], manifest["id"])
        self.assertEqual(described["version"], manifest["version"])
        self.assertEqual(described["capabilities"], manifest["capabilities"])

    def test_self_test_response_contains_no_artifacts_or_resources(self) -> None:
        request = {
            "protocol": "llm-wiki-adapter/v1",
            "adapter_id": "browser-execution",
            "operation": "self-test",
            "arguments": {},
            "options": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            request_path = root / "request.json"
            response_path = root / "response.json"
            request_path.write_text(json.dumps(request), encoding="utf-8")
            subprocess.run(
                [sys.executable, "adapter.py", "execute", "--request", str(request_path), "--response", str(response_path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            response = json.loads(response_path.read_text(encoding="utf-8"))
            self.assertEqual(response["status"], "ok")
            self.assertEqual(response["artifacts"], [])
            self.assertEqual(response["summary"]["routes"], 0)
            self.assertFalse(response["summary"]["content_embedded"])
            if os.name == "posix":
                self.assertEqual(response_path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
