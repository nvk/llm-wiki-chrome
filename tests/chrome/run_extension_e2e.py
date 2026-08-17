#!/usr/bin/env python3
"""Run a content-free read/capture smoke test in isolated Chrome for Testing."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[2]
APPROVED_ORIGINS = {"https://docs.google.com", "https://x.com"}


class IntegrationError(RuntimeError):
    """Content-free integration failure."""


def extension_id_from_key(encoded_key: str) -> str:
    try:
        digest = hashlib.sha256(base64.b64decode(encoded_key, validate=True)).digest()[:16]
    except (ValueError, TypeError) as exc:
        raise IntegrationError("invalid-extension-key") from exc
    return "".join(chr(ord("a") + nibble) for byte in digest for nibble in (byte >> 4, byte & 15))


def validate_target_url(raw_url: str) -> str:
    value = urlsplit(raw_url)
    origin = f"{value.scheme}://{value.netloc}"
    if (
        value.scheme != "https"
        or origin not in APPROVED_ORIGINS
        or value.username is not None
        or value.password is not None
        or bool(value.fragment)
        or not value.path.startswith("/")
    ):
        raise IntegrationError("target-outside-test-policy")
    return raw_url


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def request_json(method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=10) as response:
            value = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise IntegrationError("webdriver-request-failed") from exc
    if not isinstance(value, dict):
        raise IntegrationError("webdriver-response-invalid")
    return value


def wait_for_driver(base_url: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise IntegrationError("chromedriver-exited")
        try:
            status = request_json("GET", f"{base_url}/status")
            if status.get("value", {}).get("ready") is True:
                return
        except IntegrationError:
            pass
        time.sleep(0.1)
    raise IntegrationError("chromedriver-start-timeout")


def create_session(base_url: str, chrome_binary: Path, extension_dir: Path) -> tuple[str, str]:
    response = request_json(
        "POST",
        f"{base_url}/session",
        {
            "capabilities": {
                "alwaysMatch": {
                    "browserName": "chrome",
                    "goog:chromeOptions": {
                        "binary": str(chrome_binary),
                        "args": [
                            "--headless=new",
                            "--no-first-run",
                            "--no-default-browser-check",
                            f"--user-data-dir={extension_dir.parent / 'profile'}",
                            f"--disable-extensions-except={extension_dir}",
                            f"--load-extension={extension_dir}",
                        ],
                    },
                }
            }
        },
    )
    value = response.get("value")
    if not isinstance(value, dict) or not isinstance(value.get("sessionId"), str):
        raise IntegrationError("webdriver-session-failed")
    capabilities = value.get("capabilities", {})
    version = capabilities.get("browserVersion")
    if not isinstance(version, str):
        version = "unknown"
    return value["sessionId"], version


def execute_script(base_url: str, session_id: str, script: str) -> Any:
    response = request_json(
        "POST",
        f"{base_url}/session/{session_id}/execute/sync",
        {"script": script, "args": []},
    )
    return response.get("value")


def run_e2e(chrome_binary: Path, chromedriver_binary: Path, target_url: str) -> dict[str, Any]:
    if not chrome_binary.is_file() or not os.access(chrome_binary, os.X_OK):
        raise IntegrationError("chrome-binary-unavailable")
    if not chromedriver_binary.is_file() or not os.access(chromedriver_binary, os.X_OK):
        raise IntegrationError("chromedriver-binary-unavailable")
    target_url = validate_target_url(target_url)

    manifest = json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))
    extension_id = extension_id_from_key(manifest.get("key", ""))
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    session_id: str | None = None

    with tempfile.TemporaryDirectory(prefix="llm-wiki-browser-e2e-") as temporary:
        temporary_path = Path(temporary)
        extension_dir = temporary_path / "extension"
        shutil.copytree(ROOT / "extension", extension_dir)
        # The isolated harness cannot synthesize a Chrome toolbar user gesture.
        # Grant only its exact test origin in the temporary extension copy; the
        # production manifest remains activeTab-only with no host permissions.
        test_manifest_path = extension_dir / "manifest.json"
        test_manifest = json.loads(test_manifest_path.read_text(encoding="utf-8"))
        target = urlsplit(target_url)
        test_manifest["host_permissions"] = [f"{target.scheme}://{target.netloc}/*"]
        test_manifest_path.write_text(json.dumps(test_manifest), encoding="utf-8")
        for name in ("harness.html", "harness.mjs"):
            shutil.copy2(ROOT / "tests" / "chrome" / name, extension_dir / name)

        process = subprocess.Popen(
            [str(chromedriver_binary), f"--port={port}", "--log-level=WARNING"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            wait_for_driver(base_url, process)
            session_id, browser_version = create_session(base_url, chrome_binary, extension_dir)
            harness_url = (
                f"chrome-extension://{extension_id}/harness.html?target="
                f"{quote(target_url, safe='')}"
            )
            request_json(
                "POST",
                f"{base_url}/session/{session_id}/url",
                {"url": harness_url},
            )
            deadline = time.monotonic() + 45
            state: dict[str, Any] | None = None
            while time.monotonic() < deadline:
                value = execute_script(
                    base_url,
                    session_id,
                    "return {status: document.documentElement.dataset.status || '', "
                    "error: document.documentElement.dataset.error || '', "
                    "actionCount: document.documentElement.dataset.actionCount || '', "
                    "privateResultCount: document.documentElement.dataset.privateResultCount || ''};",
                )
                if isinstance(value, dict) and value.get("status") in {"pass", "error"}:
                    state = value
                    break
                time.sleep(0.1)
            if state is None:
                raise IntegrationError("extension-harness-timeout")
            if state.get("status") != "pass":
                code = state.get("error")
                if not isinstance(code, str) or not code.replace("-", "").isalnum():
                    code = "extension-harness-failed"
                raise IntegrationError(code or "extension-harness-failed")
            return {
                "status": "pass",
                "browser_version": browser_version,
                "action_count": int(state["actionCount"]),
                "private_result_count": int(state["privateResultCount"]),
            }
        finally:
            if session_id is not None:
                try:
                    request_json("DELETE", f"{base_url}/session/{session_id}")
                except IntegrationError:
                    pass
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", type=Path, required=True, help="Chrome for Testing executable")
    parser.add_argument("--chromedriver", type=Path, required=True, help="matching ChromeDriver executable")
    parser.add_argument(
        "--target-url",
        default=os.environ.get("LLM_WIKI_BROWSER_E2E_TARGET_URL"),
        help="exact approved HTTPS read target; prefer LLM_WIKI_BROWSER_E2E_TARGET_URL",
    )
    return parser.parse_args()


def main() -> int:
    arguments = parse_args()
    if not arguments.target_url:
        print("Set LLM_WIKI_BROWSER_E2E_TARGET_URL to an exact approved read target.", file=sys.stderr)
        return 2
    try:
        result = run_e2e(arguments.chrome, arguments.chromedriver, arguments.target_url)
    except IntegrationError as exc:
        print(f"Chrome integration failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
