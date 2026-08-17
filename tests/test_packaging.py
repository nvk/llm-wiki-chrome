from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_project_installs_one_unified_cli_and_extension_assets(self) -> None:
        project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn('llm-wiki-chrome = "browser_executor.cli:main"', project)
        for path in (ROOT / "extension").iterdir():
            if path.is_file():
                self.assertIn(f'"{path.relative_to(ROOT)}"', project)

    def test_cli_install_doctor_status_and_uninstall_use_one_automatic_socket(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            hosts = base / "chrome" / "NativeMessagingHosts"
            state = base / "state"
            socket_path = base / "private" / "s"
            command = base / "opt" / "bin" / "llm-wiki-chrome"
            command.parent.mkdir(parents=True)
            command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            command.chmod(0o755)
            environment = dict(os.environ)
            environment["LLM_WIKI_BROWSER_EXECUTOR_STATE_DIR"] = str(state)

            installed = self._run(
                "install",
                "--native-host-dir",
                str(hosts),
                "--native-socket",
                str(socket_path),
                "--command-path",
                str(command),
                environment=environment,
            )
            self.assertTrue(installed["installed"])
            self.assertEqual(
                installed["native_socket"], str(socket_path.resolve(strict=False))
            )

            diagnosed = self._run(
                "doctor",
                "--native-host-dir",
                str(hosts),
                "--native-socket",
                str(socket_path),
                environment=environment,
            )
            self.assertTrue(diagnosed["healthy"])
            self.assertFalse(diagnosed["connected"])

            status = self._run(
                "status",
                "--native-host-dir",
                str(hosts),
                "--native-socket",
                str(socket_path),
                environment=environment,
            )
            self.assertTrue(status["installed"])
            self.assertEqual(status["active_connector_count"], 0)

            removed = self._run(
                "uninstall",
                "--native-host-dir",
                str(hosts),
                environment=environment,
            )
            self.assertTrue(removed["uninstalled"])
            self.assertFalse((hosts / "net.llmwiki.browser_execution.json").exists())

    def test_chrome_store_zip_is_deterministic_and_contains_only_extension_assets(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.zip"
            second = Path(temporary) / "second.zip"
            for output in (first, second):
                subprocess.run(
                    [
                        sys.executable,
                        "scripts/package_extension.py",
                        "--output",
                        str(output),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=True,
                )
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(
                    archive.namelist(),
                    sorted(
                        path.name
                        for path in (ROOT / "extension").iterdir()
                        if path.is_file()
                    ),
                )
                self.assertNotIn("adapter.py", archive.namelist())

    def _run(self, *arguments: str, environment: dict[str, str]) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, "adapter.py", *arguments],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return json.loads(completed.stdout)


if __name__ == "__main__":
    unittest.main()
