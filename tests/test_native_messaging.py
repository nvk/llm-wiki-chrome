from __future__ import annotations

import io
import json
import os
import socket
import stat
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from browser_executor.native_messaging import (
    MAX_MESSAGE_BYTES,
    NATIVE_HOST_NAME,
    NativeMessagingError,
    NativeRelay,
    _valid_extension_origin,
    connector_status,
    extension_id_from_manifest,
    install_native_host,
    read_native_message,
    write_native_message,
)
from browser_executor.protocol import BROWSER_PROTOCOL
from browser_executor.storage import (
    SAFE_UNIX_SOCKET_PATH_BYTES,
    StorageError,
    native_socket_path,
    validate_private_socket,
)

ROOT = Path(__file__).resolve().parents[1]


class NativeMessagingTests(unittest.TestCase):
    def test_stable_extension_id_and_strict_origin_shape(self) -> None:
        extension_id = extension_id_from_manifest()
        self.assertRegex(extension_id, r"^[a-p]{32}$")
        self.assertTrue(_valid_extension_origin(f"chrome-extension://{extension_id}/"))
        self.assertFalse(_valid_extension_origin(f"chrome-extension://{extension_id}"))
        self.assertFalse(_valid_extension_origin("https://example.invalid/"))

    def test_native_framing_round_trip_and_limits(self) -> None:
        stream = io.BytesIO()
        value = {"protocol": BROWSER_PROTOCOL, "type": "ready"}
        write_native_message(stream, value)
        stream.seek(0)
        self.assertEqual(read_native_message(stream), value)
        oversized = io.BytesIO(struct.pack("=I", MAX_MESSAGE_BYTES + 1))
        with self.assertRaisesRegex(NativeMessagingError, "invalid size"):
            read_native_message(oversized)

    def test_native_relay_creates_private_socket_and_content_free_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            socket_path = Path(temporary) / "private" / "relay.sock"
            output = io.BytesIO()
            NativeRelay(io.BytesIO(), output, socket_path).run()
            self.assertFalse(socket_path.exists())
            output.seek(0)
            self.assertEqual(read_native_message(output), {
                "protocol": BROWSER_PROTOCOL,
                "type": "ready",
            })
            mode = stat.S_IMODE((Path(temporary) / "private").stat().st_mode)
            self.assertEqual(mode, 0o700)

    def test_second_concurrent_agent_fails_closed(self) -> None:
        relay = NativeRelay(io.BytesIO(), io.BytesIO(), Path("/tmp/synthetic-relay.sock"))
        first_relay, first_client = socket.socketpair()
        second_relay, second_client = socket.socketpair()
        try:
            relay.agent = first_relay
            relay._handle_agent(second_relay)
            error = json.loads(second_client.recv(4096).decode("utf-8"))
            self.assertEqual(error["type"], "error")
            self.assertNotIn("url", error)
        finally:
            first_relay.close()
            first_client.close()
            second_client.close()

    def test_one_agent_connection_cannot_queue_a_second_job(self) -> None:
        output = io.BytesIO()
        relay = NativeRelay(io.BytesIO(), output, Path("/tmp/synthetic-relay.sock"))
        relay_side, client_side = socket.socketpair()
        first = {
            "protocol": BROWSER_PROTOCOL,
            "type": "job",
            "job_id": "a" * 36,
        }
        second = {
            "protocol": BROWSER_PROTOCOL,
            "type": "job",
            "job_id": "b" * 36,
        }
        try:
            client_side.sendall(
                json.dumps(first, separators=(",", ":")).encode("utf-8") + b"\n" +
                json.dumps(second, separators=(",", ":")).encode("utf-8") + b"\n"
            )
            client_side.shutdown(socket.SHUT_WR)
            relay._handle_agent(relay_side)
            output.seek(0)
            self.assertEqual(read_native_message(output), first)
            self.assertIsNone(read_native_message(output))
        finally:
            client_side.close()

    def test_collaboration_workspace_is_ephemeral_exact_and_queryable(self) -> None:
        relay = NativeRelay(io.BytesIO(), io.BytesIO(), Path("/tmp/synthetic-relay.sock"))
        first = {
            "collaboration_id": "c" * 64,
            "url": "https://example.invalid/private?synthetic=1",
            "origin": "https://example.invalid",
        }
        second = {
            "collaboration_id": "d" * 64,
            "url": "https://two.invalid/private",
            "origin": "https://two.invalid",
        }
        update = {
            "protocol": BROWSER_PROTOCOL,
            "type": "collaborations",
            "selected_collaboration_id": second["collaboration_id"],
            "collaborations": [first, second],
        }
        relay._update_collaboration(update)
        relay_side, client_side = socket.socketpair()
        try:
            client_side.sendall(json.dumps({
                "protocol": BROWSER_PROTOCOL,
                "type": "collaboration-list-query",
            }, separators=(",", ":")).encode("utf-8") + b"\n")
            relay._handle_agent(relay_side)
            response = json.loads(client_side.recv(4096).decode("utf-8"))
            self.assertEqual(response["type"], "collaboration-list")
            self.assertEqual(response["selected_collaboration_id"], "d" * 64)
            self.assertEqual(response["collaborations"], [first, second])
        finally:
            client_side.close()

        relay._update_collaboration({
            "protocol": BROWSER_PROTOCOL,
            "type": "collaborations",
            "selected_collaboration_id": None,
            "collaborations": [],
        })
        self.assertEqual(relay._collaboration_status(), {
            "protocol": BROWSER_PROTOCOL,
            "type": "collaboration-status",
            "state": "inactive",
        })

    def test_collaboration_workspace_rejects_insecure_mismatched_or_duplicate_targets(self) -> None:
        relay = NativeRelay(io.BytesIO(), io.BytesIO(), Path("/tmp/synthetic-relay.sock"))
        for url, origin in (
            ("http://example.invalid/private", "http://example.invalid"),
            ("https://example.invalid/private", "https://other.invalid"),
        ):
            with self.subTest(url=url), self.assertRaises(NativeMessagingError):
                relay._update_collaboration({
                    "protocol": BROWSER_PROTOCOL,
                    "type": "collaborations",
                    "selected_collaboration_id": "c" * 64,
                    "collaborations": [{
                        "collaboration_id": "c" * 64,
                        "url": url,
                        "origin": origin,
                    }],
                })
        with self.assertRaisesRegex(NativeMessagingError, "duplicates"):
            relay._update_collaboration({
                "protocol": BROWSER_PROTOCOL,
                "type": "collaborations",
                "selected_collaboration_id": "c" * 64,
                "collaborations": [
                    {
                        "collaboration_id": "c" * 64,
                        "url": "https://example.invalid/one",
                        "origin": "https://example.invalid",
                    },
                    {
                        "collaboration_id": "d" * 64,
                        "url": "https://example.invalid/one",
                        "origin": "https://example.invalid",
                    },
                ],
            })

    def test_installer_pins_exact_extension_origin_and_private_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            repository = base / "repository"
            (repository / ".venv" / "bin").mkdir(parents=True)
            os.symlink(sys.executable, repository / ".venv" / "bin" / "python")
            (repository / "adapter.py").write_text("raise SystemExit(0)\n", encoding="utf-8")
            (repository / "extension").mkdir()
            (repository / "extension" / "manifest.json").write_text(
                (ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            hosts = base / "chrome" / "NativeMessagingHosts"
            state = base / "state"
            with mock.patch.dict(os.environ, {
                "LLM_WIKI_BROWSER_EXECUTOR_STATE_DIR": str(state),
                "LLM_WIKI_BROWSER_EXECUTOR_NATIVE_SOCKET": str(state / "relay.sock"),
            }, clear=False):
                installed = install_native_host(repository, hosts)
                manifest = json.loads(installed["manifest_path"].read_text(encoding="utf-8"))
                extension_id = extension_id_from_manifest(repository / "extension" / "manifest.json")
                self.assertEqual(manifest["name"], NATIVE_HOST_NAME)
                self.assertEqual(manifest["allowed_origins"], [f"chrome-extension://{extension_id}/"])
                self.assertEqual(stat.S_IMODE(installed["manifest_path"].stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(installed["wrapper_path"].stat().st_mode), 0o700)
                self.assertEqual(connector_status(hosts)["installed"], True)

    def test_long_state_path_uses_private_short_socket_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            long_root = Path(temporary) / ("x" * 100) / ("y" * 100)
            with mock.patch.dict(os.environ, {
                "LLM_WIKI_BROWSER_EXECUTOR_STATE_DIR": str(long_root),
            }, clear=False):
                path = native_socket_path()
                self.assertLessEqual(len(os.fsencode(str(path))), SAFE_UNIX_SOCKET_PATH_BYTES)
                self.assertEqual(path.parent.parent, Path("/tmp"))

    def test_socket_owner_modes_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "relay.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(path))
                path.chmod(0o600)
                validate_private_socket(path)
                path.chmod(0o666)
                with self.assertRaisesRegex(StorageError, "private user socket"):
                    validate_private_socket(path)
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()
