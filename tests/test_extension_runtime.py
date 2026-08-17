from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ExtensionRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is required for extension runtime tests")
    def test_typed_executor_runtime(self) -> None:
        completed = subprocess.run(
            ["node", "tests/js/test-executor.mjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ok\n")

    @unittest.skipUnless(shutil.which("node"), "Node is required for extension runtime tests")
    def test_service_worker_orchestration(self) -> None:
        completed = subprocess.run(
            ["node", "tests/js/test-service-worker.mjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "ok\n")


if __name__ == "__main__":
    unittest.main()
