#!/usr/bin/env python3
"""Content-free entrypoint for the private bounded browser executor."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from browser_executor.native_messaging import (
    connector_status,
    extension_root,
    install_native_host,
    run_native_host,
)
from browser_executor.protocol import BROWSER_PROTOCOL, canonical_program_sha256, validate_program

ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / ".llm-wiki-adapter.json"


def load_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def describe() -> int:
    manifest = load_manifest()
    print(json.dumps({
        "protocol": manifest["protocol"],
        "id": manifest["id"],
        "version": manifest["version"],
        "capabilities": manifest["capabilities"],
    }, sort_keys=True))
    return 0


def synthetic_program() -> dict[str, Any]:
    program = {
        "protocol": BROWSER_PROTOCOL,
        "program_id": "synthetic-self-test",
        "plan_sha256": "0" * 64,
        "driver": {"id": "synthetic-driver", "version": "1"},
        "capability": "read",
        "target": {
            "url": "https://x.com/i/spaces/SYNTHETIC_SELF_TEST",
            "origin": "https://x.com",
            "path_prefixes": ["/i/spaces/SYNTHETIC_SELF_TEST"],
        },
        "limits": {"timeout_ms": 1000, "max_actions": 4, "max_repeat": 1},
        "private_slots": [],
        "actions": [
            {"op": "open_or_focus_exact_url"},
            {"op": "assert_exact_target"},
            {"op": "attach_debugger"},
            {"op": "detach_debugger"},
        ],
        "result": {"public_fields": ["status", "action_count"], "private_fields": []},
    }
    program["program_sha256"] = canonical_program_sha256(program)
    return program


def execute(request_path: Path, response_path: Path) -> int:
    manifest = load_manifest()
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if request.get("protocol") != manifest["protocol"]:
            raise ValueError("unsupported protocol")
        if request.get("adapter_id") != manifest["id"]:
            raise ValueError("wrong adapter_id")
        if request.get("operation") != "self-test":
            raise ValueError("unsupported operation")
        if not isinstance(request.get("arguments"), dict):
            raise ValueError("arguments must be an object")
        if not isinstance(request.get("options", {}), dict):
            raise ValueError("options must be an object")
        program = validate_program(synthetic_program())
        seed = json.dumps({
            "adapter_id": manifest["id"],
            "version": manifest["version"],
            "operation": "self-test",
            "program_sha256": canonical_program_sha256(program),
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
        response = {
            "protocol": manifest["protocol"],
            "adapter_id": manifest["id"],
            "adapter_version": manifest["version"],
            "operation": "self-test",
            "status": "ok",
            "run_id": hashlib.sha256(seed).hexdigest(),
            "summary": {
                "tool_only": True,
                "content_embedded": False,
                "routes": 0,
                "browser_protocol": BROWSER_PROTOCOL,
                "typed_program_valid": True,
            },
            "artifacts": [],
        }
        code = 0
    except Exception as exc:
        response = {
            "protocol": manifest.get("protocol", "llm-wiki-adapter/v1"),
            "adapter_id": manifest.get("id", "browser-execution"),
            "adapter_version": manifest.get("version", "unknown"),
            "operation": "self-test",
            "status": "error",
            "summary": {"tool_only": True, "content_embedded": False},
            "errors": [str(exc)],
            "artifacts": [],
        }
        code = 2
    response_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = response_path.with_suffix(response_path.suffix + ".tmp")
    temporary.write_text(json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, response_path)
    response_path.chmod(0o600)
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("describe")
    run = sub.add_parser("execute")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--response", type=Path, required=True)
    sub.add_parser("browser-install")
    sub.add_parser("browser-status")
    sub.add_parser("extension-path")
    native = sub.add_parser("native-host")
    native.add_argument("origin", nargs="?")
    args = parser.parse_args(argv)
    if args.command == "describe":
        return describe()
    if args.command == "execute":
        return execute(args.request, args.response)
    if args.command == "browser-install":
        installed = install_native_host(ROOT)
        print(json.dumps({
            "installed": True,
            "extension_id": installed["extension_id"],
            "extension_path": str(extension_root()),
        }, sort_keys=True))
        return 0
    if args.command == "browser-status":
        print(json.dumps(connector_status(), sort_keys=True))
        return 0
    if args.command == "extension-path":
        print(extension_root())
        return 0
    run_native_host(args.origin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
