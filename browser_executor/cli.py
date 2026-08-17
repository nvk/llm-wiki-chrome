#!/usr/bin/env python3
"""Packaged CLI for LLM Wiki for Chrome and its private connector."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

from .native_messaging import (
    NATIVE_HOST_NAME,
    NATIVE_HOST_SCHEMA,
    chrome_native_host_dir,
    connector_status,
    extension_root,
    installed_cli_path,
    install_native_host,
    run_native_host,
    uninstall_native_host,
)
from .client import BrowserExecutorClient
from .collaboration import BrowserCollaborationController
from .mcp_server import run_mcp_server
from .protocol import BROWSER_PROTOCOL, canonical_program_sha256, validate_program
from .storage import (
    NATIVE_SOCKET_INSTANCE_SUFFIX_BYTES,
    SAFE_UNIX_SOCKET_PATH_BYTES,
    StorageError,
    native_socket_candidates,
    native_socket_path,
    state_root,
    validate_private_socket,
)

SOURCE_ROOT = Path(__file__).resolve().parents[1]


def manifest_path() -> Path:
    source = SOURCE_ROOT / ".llm-wiki-adapter.json"
    if source.is_file():
        return source
    installed = (
        Path(sys.prefix) / "share" / "llm-wiki-chrome" / ".llm-wiki-adapter.json"
    )
    if installed.is_file():
        return installed
    raise RuntimeError("packaged adapter manifest is missing")


def load_manifest() -> dict[str, Any]:
    return json.loads(manifest_path().read_text(encoding="utf-8"))


def describe() -> int:
    manifest = load_manifest()
    print(
        json.dumps(
            {
                "protocol": manifest["protocol"],
                "id": manifest["id"],
                "version": manifest["version"],
                "capabilities": manifest["capabilities"],
            },
            sort_keys=True,
        )
    )
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
            "collaboration_id": "f" * 64,
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
        seed = json.dumps(
            {
                "adapter_id": manifest["id"],
                "version": manifest["version"],
                "operation": "self-test",
                "program_sha256": canonical_program_sha256(program),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
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
    temporary.write_text(
        json.dumps(response, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temporary.chmod(0o600)
    os.replace(temporary, response_path)
    response_path.chmod(0o600)
    return code


def doctor(destination: Path | None = None, socket_path: Path | None = None) -> int:
    status = connector_status(destination=destination, socket_path=socket_path)
    extension = json.loads(
        (extension_root() / "manifest.json").read_text(encoding="utf-8")
    )
    adapter = load_manifest()
    socket_base = (
        (socket_path or native_socket_path()).expanduser().resolve(strict=False)
    )
    sockets = native_socket_candidates(socket_base)
    install_dir = (
        (destination or chrome_native_host_dir()).expanduser().resolve(strict=False)
    )
    manifest = install_dir / f"{NATIVE_HOST_NAME}.json"
    metadata = state_root() / "native-host-installation.json"
    launcher = state_root() / "native-host"
    issues: list[str] = []
    if adapter.get("version") != extension.get("version"):
        issues.append("adapter and extension versions differ")
    if extension.get("name") != "LLM Wiki for Chrome":
        issues.append("packaged extension identity is invalid")
    if not status["installed"]:
        issues.append("Chrome native messaging host is not installed correctly")
    if (
        len(os.fsencode(str(socket_base))) + NATIVE_SOCKET_INSTANCE_SUFFIX_BYTES
        > SAFE_UNIX_SOCKET_PATH_BYTES
    ):
        issues.append("native connector socket path is too long")
    for label, path, expected_mode in (
        ("native messaging manifest", manifest, 0o600),
        ("native host launcher", launcher, 0o700),
        ("installation metadata", metadata, 0o600),
    ):
        if path.exists() and stat.S_IMODE(path.stat().st_mode) != expected_mode:
            issues.append(f"{label} permissions are invalid")
    if metadata.is_file():
        try:
            installed = json.loads(metadata.read_text(encoding="utf-8"))
            if (
                installed.get("schema") != NATIVE_HOST_SCHEMA
                or installed.get("extension_id") != status["extension_id"]
                or installed.get("manifest_path") != str(manifest)
                or installed.get("socket_path") != str(socket_base)
            ):
                issues.append("native host installation metadata does not match")
        except (OSError, json.JSONDecodeError):
            issues.append("native host installation metadata is unreadable")
    for live_socket in sockets:
        try:
            validate_private_socket(live_socket)
        except StorageError:
            issues.append("a live native connector is not private")
            break
    result = {
        "healthy": not issues,
        "installed": status["installed"],
        "connected": status["connected"],
        "active_connector_count": len(sockets),
        "extension_id": status["extension_id"],
        "extension_version": extension.get("version"),
        "issues": issues,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if not issues else 2


def _install_parser(
    sub: argparse._SubParsersAction[argparse.ArgumentParser], name: str
) -> None:
    install = sub.add_parser(name)
    install.add_argument("--native-socket", type=Path)
    install.add_argument("--native-host-dir", type=Path)
    install.add_argument("--command-path", type=Path, help=argparse.SUPPRESS)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("describe")
    run = sub.add_parser("execute")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--response", type=Path, required=True)
    _install_parser(sub, "install")
    _install_parser(sub, "browser-install")
    uninstall = sub.add_parser("uninstall")
    uninstall.add_argument("--native-host-dir", type=Path)
    status = sub.add_parser("status")
    status.add_argument("--native-socket", type=Path)
    status.add_argument("--native-host-dir", type=Path)
    browser_status = sub.add_parser("browser-status")
    browser_status.add_argument("--native-socket", type=Path)
    browser_status.add_argument("--native-host-dir", type=Path)
    diagnose = sub.add_parser("doctor")
    diagnose.add_argument("--native-socket", type=Path)
    diagnose.add_argument("--native-host-dir", type=Path)
    sub.add_parser("browser-tabs")
    sub.add_parser("browser-agent-status")
    snapshot = sub.add_parser("browser-snapshot")
    snapshot.add_argument("--collaboration-id", required=True)
    snapshot.add_argument("--max-items", type=int, default=400)
    sub.add_parser("mcp-server")
    sub.add_parser("extension-path")
    native = sub.add_parser("native-host")
    native.add_argument("origin", nargs="?")
    args = parser.parse_args(argv)
    if args.command == "describe":
        return describe()
    if args.command == "execute":
        return execute(args.request, args.response)
    if args.command in {"install", "browser-install"}:
        command = args.command_path
        if command is None and args.command == "install":
            command = installed_cli_path()
        root = SOURCE_ROOT if command is None else None
        installed = install_native_host(
            root,
            destination=args.native_host_dir,
            socket_path=args.native_socket,
            command_path=command,
        )
        print(
            json.dumps(
                {
                    "installed": True,
                    "extension_id": installed["extension_id"],
                    "extension_path": str(extension_root()),
                    "native_socket": str(installed["socket_path"]),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "uninstall":
        print(
            json.dumps(
                uninstall_native_host(destination=args.native_host_dir), sort_keys=True
            )
        )
        return 0
    if args.command in {"status", "browser-status"}:
        value = connector_status(
            destination=args.native_host_dir, socket_path=args.native_socket
        )
        value["active_connector_count"] = len(
            native_socket_candidates(args.native_socket or native_socket_path())
        )
        print(json.dumps(value, sort_keys=True))
        return 0
    if args.command == "doctor":
        return doctor(destination=args.native_host_dir, socket_path=args.native_socket)
    if args.command == "browser-tabs":
        print(
            json.dumps(
                {"tabs": BrowserExecutorClient().collaborations()}, sort_keys=True
            )
        )
        return 0
    if args.command == "browser-agent-status":
        print(json.dumps(BrowserCollaborationController().status(), sort_keys=True))
        return 0
    if args.command == "browser-snapshot":
        value = BrowserCollaborationController().snapshot(
            args.collaboration_id,
            max_items=args.max_items,
        )
        print(json.dumps(value, sort_keys=True, ensure_ascii=False))
        return 0
    if args.command == "mcp-server":
        return run_mcp_server()
    if args.command == "extension-path":
        print(extension_root())
        return 0
    run_native_host(args.origin)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
