from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlsplit

from .protocol import BROWSER_PROTOCOL
from .storage import (
    SAFE_UNIX_SOCKET_PATH_BYTES,
    ensure_private_directory,
    ensure_socket_parent,
    native_socket_path,
    state_root,
    write_private_json,
)

NATIVE_HOST_NAME = "net.llmwiki.browser_execution"
NATIVE_HOST_SCHEMA = "llm-wiki-browser-native-host/v1"
EXTENSION_ORIGIN_PREFIX = "chrome-extension://"
MAX_MESSAGE_BYTES = 1_048_576
COLLABORATION_ID = re.compile(r"^[a-f0-9]{64}$")
MAX_COLLABORATIONS = 16


class NativeMessagingError(RuntimeError):
    """Raised when installation, framing, or local relay behavior is invalid."""


def extension_root() -> Path:
    return Path(__file__).resolve().parents[1] / "extension"


def _c_bytes(name: str, value: Path) -> str:
    encoded = os.fsencode(str(value)) + b"\0"
    return f"static const char {name}[] = {{{','.join(str(byte) for byte in encoded)}}};\n"


def _install_launcher(wrapper: Path, python: Path, entrypoint: Path, socket_path: Path) -> None:
    if sys.platform != "darwin":
        script = (
            "#!/bin/sh\n"
            f"export LLM_WIKI_BROWSER_EXECUTOR_NATIVE_SOCKET={shlex.quote(str(socket_path))}\n"
            f"exec {shlex.quote(str(python))} {shlex.quote(str(entrypoint))} native-host \"$@\"\n"
        )
        wrapper.write_text(script, encoding="utf-8")
        wrapper.chmod(0o700)
        return
    compiler = Path("/usr/bin/clang")
    if not compiler.is_file() or not os.access(compiler, os.X_OK):
        raise NativeMessagingError("macOS native-host installation requires /usr/bin/clang")
    source = (
        "#include <stdlib.h>\n#include <unistd.h>\n#include <stdio.h>\n"
        + _c_bytes("PYTHON_PATH", python)
        + _c_bytes("ADAPTER_PATH", entrypoint)
        + _c_bytes("SOCKET_PATH", socket_path)
        + r'''
int main(int argc, char **argv) {
  if (setenv("LLM_WIKI_BROWSER_EXECUTOR_NATIVE_SOCKET", SOCKET_PATH, 1) != 0) return 126;
  char **args = calloc((size_t)argc + 4, sizeof(char *));
  if (!args) return 126;
  args[0] = (char *)PYTHON_PATH;
  args[1] = (char *)ADAPTER_PATH;
  args[2] = "native-host";
  for (int i = 1; i < argc; i++) args[i + 2] = argv[i];
  args[argc + 2] = NULL;
  execv(PYTHON_PATH, args);
  perror("execv");
  return 127;
}
'''
    )
    with tempfile.TemporaryDirectory(prefix="native-host-build-", dir=wrapper.parent) as build:
        build_root = Path(build)
        source_path = build_root / "launcher.c"
        output_path = build_root / "native-host"
        source_path.write_text(source, encoding="utf-8")
        result = subprocess.run(
            [str(compiler), "-Os", "-o", str(output_path), str(source_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if result.returncode != 0 or not output_path.is_file():
            raise NativeMessagingError("could not compile the macOS native-host launcher")
        output_path.chmod(0o700)
        os.replace(output_path, wrapper)
        wrapper.chmod(0o700)


def extension_id_from_manifest(manifest_path: Path | None = None) -> str:
    path = manifest_path or (extension_root() / "manifest.json")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        public_key = base64.b64decode(manifest["key"], validate=True)
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise NativeMessagingError("extension manifest has no valid stable public key") from exc
    prefix = hashlib.sha256(public_key).digest()[:16].hex()
    return prefix.translate(str.maketrans("0123456789abcdef", "abcdefghijklmnop"))


def chrome_native_host_dir() -> Path:
    override = os.environ.get("LLM_WIKI_CHROME_NATIVE_HOST_DIR")
    if override:
        return Path(override).expanduser().resolve(strict=False)
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Google" / "Chrome" / "NativeMessagingHosts"
    if os.name == "posix":
        return Path.home() / ".config" / "google-chrome" / "NativeMessagingHosts"
    raise NativeMessagingError("automatic native-host installation supports macOS and Linux")


def install_native_host(
    root: Path | None = None,
    destination: Path | None = None,
    socket_path: Path | None = None,
) -> dict[str, Any]:
    repository = (root or Path(__file__).resolve().parents[1]).resolve(strict=True)
    python = repository / ".venv" / "bin" / "python"
    entrypoint = repository / "adapter.py"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise NativeMessagingError("adapter virtual environment is missing or not executable")
    if not entrypoint.is_file():
        raise NativeMessagingError("adapter entrypoint is missing")
    install_dir = (destination or chrome_native_host_dir()).resolve(strict=False)
    ensure_private_directory(install_dir)
    extension_id = extension_id_from_manifest(repository / "extension" / "manifest.json")
    durable_root = state_root()
    ensure_private_directory(durable_root)
    connector_path = (socket_path or native_socket_path()).expanduser().resolve(strict=False)
    if len(os.fsencode(str(connector_path))) > SAFE_UNIX_SOCKET_PATH_BYTES:
        raise NativeMessagingError("native connector socket path is too long")
    ensure_socket_parent(connector_path)
    wrapper = durable_root / "native-host"
    _install_launcher(wrapper, python, entrypoint, connector_path)
    manifest_path = install_dir / f"{NATIVE_HOST_NAME}.json"
    write_private_json(manifest_path, {
        "name": NATIVE_HOST_NAME,
        "description": "Local bounded LLM Wiki browser executor",
        "path": str(wrapper),
        "type": "stdio",
        "allowed_origins": [f"{EXTENSION_ORIGIN_PREFIX}{extension_id}/"],
    })
    write_private_json(durable_root / "native-host-installation.json", {
        "schema": NATIVE_HOST_SCHEMA,
        "extension_id": extension_id,
        "manifest_path": str(manifest_path),
    })
    return {
        "extension_id": extension_id,
        "manifest_path": manifest_path,
        "wrapper_path": wrapper,
        "socket_path": connector_path,
    }


def connector_status(
    destination: Path | None = None,
    socket_path: Path | None = None,
) -> dict[str, Any]:
    install_dir = (destination or chrome_native_host_dir()).resolve(strict=False)
    manifest_path = install_dir / f"{NATIVE_HOST_NAME}.json"
    installed = False
    if manifest_path.is_file():
        try:
            value = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected = f"{EXTENSION_ORIGIN_PREFIX}{extension_id_from_manifest()}/"
            installed = (
                value.get("name") == NATIVE_HOST_NAME
                and value.get("type") == "stdio"
                and value.get("allowed_origins") == [expected]
                and Path(str(value.get("path", ""))) == state_root() / "native-host"
                and Path(str(value.get("path", ""))).is_file()
            )
        except (OSError, ValueError, json.JSONDecodeError, NativeMessagingError):
            installed = False
    return {
        "installed": installed,
        "connected": (socket_path or native_socket_path()).expanduser().resolve(strict=False).is_socket(),
        "extension_id": extension_id_from_manifest(),
    }


def read_native_message(stream: BinaryIO) -> dict[str, Any] | None:
    header = stream.read(4)
    if not header:
        return None
    if len(header) != 4:
        raise NativeMessagingError("native message header is truncated")
    length = struct.unpack("=I", header)[0]
    if length <= 0 or length > MAX_MESSAGE_BYTES:
        raise NativeMessagingError("native message has an invalid size")
    payload = stream.read(length)
    if len(payload) != length:
        raise NativeMessagingError("native message is truncated")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeMessagingError("native message is not valid JSON") from exc
    if not isinstance(value, dict):
        raise NativeMessagingError("native message must be a JSON object")
    return value


def write_native_message(stream: BinaryIO, value: dict[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise NativeMessagingError("native message is too large")
    stream.write(struct.pack("=I", len(payload)))
    stream.write(payload)
    stream.flush()


def _valid_extension_origin(value: str) -> bool:
    if not value.startswith(EXTENSION_ORIGIN_PREFIX) or not value.endswith("/"):
        return False
    extension_id = value[len(EXTENSION_ORIGIN_PREFIX):-1]
    return len(extension_id) == 32 and all(character in "abcdefghijklmnop" for character in extension_id)


def _validate_collaboration(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"collaboration_id", "url", "origin"}:
        raise NativeMessagingError("active collaboration state has an invalid shape")
    collaboration_id = value.get("collaboration_id")
    raw_url = value.get("url")
    raw_origin = value.get("origin")
    if (
        not isinstance(collaboration_id, str)
        or not COLLABORATION_ID.fullmatch(collaboration_id)
        or not isinstance(raw_url, str)
        or not isinstance(raw_origin, str)
        or len(raw_url.encode("utf-8")) > 16_384
    ):
        raise NativeMessagingError("active collaboration state is invalid")
    url = urlsplit(raw_url)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or raw_origin != f"{url.scheme}://{url.netloc}"
    ):
        raise NativeMessagingError("active collaboration target is invalid")
    return {
        "collaboration_id": collaboration_id,
        "url": raw_url,
        "origin": raw_origin,
    }


def _validate_collaboration_update(value: dict[str, Any]) -> dict[str, Any]:
    if set(value) != {
        "protocol", "type", "selected_collaboration_id", "collaborations",
    } or value.get("type") != "collaborations":
        raise NativeMessagingError("extension collaboration workspace is invalid")
    raw_collaborations = value.get("collaborations")
    if not isinstance(raw_collaborations, list) or len(raw_collaborations) > MAX_COLLABORATIONS:
        raise NativeMessagingError("extension collaboration workspace is invalid")
    collaborations = [_validate_collaboration(item) for item in raw_collaborations]
    identifiers = {item["collaboration_id"] for item in collaborations}
    urls = {item["url"] for item in collaborations}
    if len(identifiers) != len(collaborations) or len(urls) != len(collaborations):
        raise NativeMessagingError("extension collaboration workspace contains duplicates")
    selected = value.get("selected_collaboration_id")
    if selected is not None and (
        not isinstance(selected, str)
        or not COLLABORATION_ID.fullmatch(selected)
        or selected not in identifiers
    ):
        raise NativeMessagingError("extension selected collaboration is invalid")
    return {
        "selected_collaboration_id": selected,
        "collaborations": collaborations,
    }


class NativeRelay:
    """Relay one local targeted-adapter connection to the shared extension."""

    def __init__(self, input_stream: BinaryIO, output_stream: BinaryIO, socket_path: Path) -> None:
        self.input_stream = input_stream
        self.output_stream = output_stream
        self.socket_path = socket_path
        self.output_lock = threading.Lock()
        self.agent_lock = threading.Lock()
        self.agent: socket.socket | None = None
        self.server: socket.socket | None = None
        self.collaboration_lock = threading.Lock()
        self.workspace: dict[str, Any] = {
            "selected_collaboration_id": None,
            "collaborations": [],
        }

    def _write_extension(self, value: dict[str, Any]) -> None:
        with self.output_lock:
            write_native_message(self.output_stream, value)

    def _write_agent(self, value: dict[str, Any]) -> None:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(payload) > MAX_MESSAGE_BYTES:
            raise NativeMessagingError("relay message is too large")
        with self.agent_lock:
            if self.agent is not None:
                self.agent.sendall(payload + b"\n")

    def _collaboration_status(self) -> dict[str, Any]:
        with self.collaboration_lock:
            selected = self.workspace["selected_collaboration_id"]
            current = next((
                dict(item) for item in self.workspace["collaborations"]
                if item["collaboration_id"] == selected
            ), None)
        if current is None:
            return {
                "protocol": BROWSER_PROTOCOL,
                "type": "collaboration-status",
                "state": "inactive",
            }
        return {
            "protocol": BROWSER_PROTOCOL,
            "type": "collaboration-status",
            "state": "active",
            **current,
        }

    def _collaboration_list(self) -> dict[str, Any]:
        with self.collaboration_lock:
            workspace = {
                "selected_collaboration_id": self.workspace["selected_collaboration_id"],
                "collaborations": [dict(item) for item in self.workspace["collaborations"]],
            }
        return {
            "protocol": BROWSER_PROTOCOL,
            "type": "collaboration-list",
            **workspace,
        }

    def _update_collaboration(self, value: dict[str, Any]) -> None:
        workspace = _validate_collaboration_update(value)
        with self.collaboration_lock:
            self.workspace = workspace

    def _handle_agent(self, connection: socket.socket) -> None:
        with self.agent_lock:
            if self.agent is not None:
                connection.sendall(json.dumps({
                    "protocol": BROWSER_PROTOCOL,
                    "type": "error",
                    "error": "another bounded browser job is already active",
                }, separators=(",", ":")).encode("utf-8") + b"\n")
                connection.close()
                return
            self.agent = connection
        buffer = bytearray()
        job_id: str | None = None
        mutation_reply_seen = False
        try:
            while True:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > MAX_MESSAGE_BYTES:
                    raise NativeMessagingError("agent relay message is too large")
                while b"\n" in buffer:
                    line, _, remainder = bytes(buffer).partition(b"\n")
                    buffer.clear()
                    buffer.extend(remainder)
                    value = json.loads(line.decode("utf-8"))
                    if not isinstance(value, dict) or value.get("protocol") != BROWSER_PROTOCOL:
                        raise NativeMessagingError("agent relay protocol is invalid")
                    message_type = value.get("type")
                    if job_id is None and message_type == "collaboration-query":
                        if set(value) != {"protocol", "type"}:
                            raise NativeMessagingError("collaboration query has an invalid shape")
                        payload = json.dumps(
                            self._collaboration_status(),
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        connection.sendall(payload + b"\n")
                        return
                    if job_id is None and message_type == "collaboration-list-query":
                        if set(value) != {"protocol", "type"}:
                            raise NativeMessagingError("collaboration list query has an invalid shape")
                        payload = json.dumps(
                            self._collaboration_list(),
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8")
                        connection.sendall(payload + b"\n")
                        return
                    incoming_job_id = value.get("job_id")
                    valid_job_id = (
                        isinstance(incoming_job_id, str)
                        and len(incoming_job_id) == 36
                        and all(character in "0123456789abcdef" for character in incoming_job_id)
                    )
                    if job_id is None:
                        if message_type != "job" or not valid_job_id:
                            raise NativeMessagingError("agent relay requires one bounded job")
                        job_id = incoming_job_id
                    elif (
                        message_type != "mutation-authorized"
                        or incoming_job_id != job_id
                        or mutation_reply_seen
                        or not isinstance(value.get("authorized"), bool)
                    ):
                        raise NativeMessagingError("agent relay rejected a second or mismatched job")
                    else:
                        mutation_reply_seen = True
                    self._write_extension(value)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, NativeMessagingError):
            pass
        finally:
            with self.agent_lock:
                if self.agent is connection:
                    self.agent = None
            connection.close()

    def _accept_agents(self) -> None:
        assert self.server is not None
        while True:
            try:
                connection, _address = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._handle_agent, args=(connection,), daemon=True).start()

    def run(self) -> None:
        ensure_socket_parent(self.socket_path)
        if self.socket_path.exists() or self.socket_path.is_symlink():
            if self.socket_path.is_socket() or self.socket_path.is_symlink():
                self.socket_path.unlink()
            else:
                raise NativeMessagingError("native connector socket path is not a socket")
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            self.server.bind(str(self.socket_path))
            self.socket_path.chmod(0o600)
            self.server.listen(2)
            threading.Thread(target=self._accept_agents, daemon=True).start()
            self._write_extension({"protocol": BROWSER_PROTOCOL, "type": "ready"})
            while True:
                value = read_native_message(self.input_stream)
                if value is None:
                    return
                if value.get("protocol") != BROWSER_PROTOCOL:
                    self._write_extension({
                        "protocol": BROWSER_PROTOCOL,
                        "type": "error",
                        "error": "extension protocol does not match native host",
                    })
                    continue
                if value.get("type") == "collaborations":
                    try:
                        self._update_collaboration(value)
                    except NativeMessagingError:
                        self._write_extension({
                            "protocol": BROWSER_PROTOCOL,
                            "type": "error",
                            "error": "extension collaboration state is invalid",
                        })
                    continue
                self._write_agent(value)
        finally:
            if self.server is not None:
                self.server.close()
            with self.agent_lock:
                if self.agent is not None:
                    self.agent.close()
                    self.agent = None
            try:
                if self.socket_path.is_socket() or self.socket_path.is_symlink():
                    self.socket_path.unlink()
            except OSError:
                pass


def run_native_host(origin: str | None = None) -> None:
    caller = origin or (sys.argv[1] if len(sys.argv) > 1 else "")
    if not _valid_extension_origin(caller):
        raise NativeMessagingError("native host caller is not a Chrome extension")
    expected = f"{EXTENSION_ORIGIN_PREFIX}{extension_id_from_manifest()}/"
    if caller != expected:
        raise NativeMessagingError("native host caller is not the installed browser executor")
    NativeRelay(sys.stdin.buffer, sys.stdout.buffer, native_socket_path()).run()
