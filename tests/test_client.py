from __future__ import annotations

import json
import socket
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Callable

from browser_executor.client import BrowserExecutorClient, ClientError
from browser_executor.protocol import BROWSER_PROTOCOL, ProtocolError

ROOT = Path(__file__).resolve().parents[1]


def fixture(name: str) -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))


def receive_line(connection: socket.socket) -> dict:
    buffer = bytearray()
    while b"\n" not in buffer:
        chunk = connection.recv(65536)
        if not chunk:
            raise RuntimeError("client disconnected")
        buffer.extend(chunk)
    return json.loads(bytes(buffer).partition(b"\n")[0])


def send_line(connection: socket.socket, value: dict) -> None:
    connection.sendall(json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n")


class ClientTests(unittest.TestCase):
    def run_server(
        self,
        program: dict,
        handler: Callable[[socket.socket, dict], None],
        **client_kwargs,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "executor.sock"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            server.bind(str(path))
            path.chmod(0o600)
            server.listen(1)
            failures: list[BaseException] = []

            def serve() -> None:
                try:
                    connection, _ = server.accept()
                    with connection:
                        handler(connection, receive_line(connection))
                except BaseException as exc:  # surfaced in the test thread
                    failures.append(exc)
                finally:
                    server.close()

            thread = threading.Thread(target=serve, daemon=True)
            thread.start()
            try:
                result = BrowserExecutorClient(path, timeout_seconds=10).run(program, **client_kwargs)
            finally:
                thread.join(timeout=2)
            if failures:
                raise failures[0]
            self.assertFalse(thread.is_alive())
            return result

    def test_read_job_round_trip_keeps_extraction_private(self) -> None:
        program = fixture("x-space-read-v1.json")

        def handler(connection: socket.socket, job: dict) -> None:
            self.assertEqual(job["protocol"], BROWSER_PROTOCOL)
            self.assertEqual(job["private_values"], {})
            send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": "result",
                "job_id": job["job_id"],
                "status": "ok",
                "public": {"status": "ok", "action_count": 8, "private_result_count": 2},
                "private": {"space.attendees": [{"name": "Synthetic"}], "space.metadata": {"name": "Synthetic"}},
            })

        result = self.run_server(program, handler)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(set(result["private"]), {"space.attendees", "space.metadata"})

    def test_mutation_requires_and_crosses_one_callback_boundary(self) -> None:
        program = fixture("google-docs-suggestions-v1.json")
        callback_count = 0

        def callback() -> None:
            nonlocal callback_count
            callback_count += 1

        def handler(connection: socket.socket, job: dict) -> None:
            self.assertEqual(set(job["private_values"]), {"edit.find", "edit.replace"})
            send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": "before-mutation",
                "job_id": job["job_id"],
            })
            authorization = receive_line(connection)
            self.assertTrue(authorization["authorized"])
            send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": "result",
                "job_id": job["job_id"],
                "status": "ok",
                "public": {"status": "ok", "action_count": 24, "mutation_started": True},
                "private": {},
            })

        result = self.run_server(
            program,
            handler,
            private_values={"edit.find": "synthetic old", "edit.replace": "synthetic new"},
            before_mutation=callback,
        )
        self.assertEqual(callback_count, 1)
        self.assertTrue(result["public"]["mutation_started"])

    def test_mutation_without_callback_is_rejected_before_connect(self) -> None:
        program = fixture("google-docs-suggestions-v1.json")
        with self.assertRaisesRegex(ProtocolError, "before_mutation"):
            BrowserExecutorClient(Path("/tmp/absent-executor.sock")).run(
                program,
                private_values={"edit.find": "synthetic", "edit.replace": "synthetic"},
            )

    def test_callback_failure_sends_denial(self) -> None:
        program = fixture("google-docs-suggestions-v1.json")

        def handler(connection: socket.socket, job: dict) -> None:
            send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": "before-mutation",
                "job_id": job["job_id"],
            })
            self.assertFalse(receive_line(connection)["authorized"])

        def reject() -> None:
            raise RuntimeError("synthetic precondition failed")

        with self.assertRaisesRegex(RuntimeError, "synthetic precondition"):
            self.run_server(
                program,
                handler,
                private_values={"edit.find": "synthetic", "edit.replace": "synthetic"},
                before_mutation=reject,
            )

    def test_duplicate_mutation_boundary_fails_closed(self) -> None:
        program = fixture("google-docs-suggestions-v1.json")

        def handler(connection: socket.socket, job: dict) -> None:
            boundary = {"protocol": BROWSER_PROTOCOL, "type": "before-mutation", "job_id": job["job_id"]}
            send_line(connection, boundary)
            self.assertTrue(receive_line(connection)["authorized"])
            send_line(connection, boundary)

        with self.assertRaisesRegex(ClientError, "repeated"):
            self.run_server(
                program,
                handler,
                private_values={"edit.find": "synthetic", "edit.replace": "synthetic"},
                before_mutation=lambda: None,
            )

    def test_undeclared_public_result_is_rejected(self) -> None:
        program = fixture("x-space-read-v1.json")

        def handler(connection: socket.socket, job: dict) -> None:
            send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": "result",
                "job_id": job["job_id"],
                "status": "ok",
                "public": {"url": "synthetic"},
                "private": {},
            })

        with self.assertRaisesRegex(ClientError, "undeclared public"):
            self.run_server(program, handler)

    def test_result_error_must_be_a_content_free_code(self) -> None:
        program = fixture("x-space-read-v1.json")

        def handler(connection: socket.socket, job: dict) -> None:
            send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": "result",
                "job_id": job["job_id"],
                "status": "error",
                "public": {"status": "error", "action_count": 0},
                "private": {},
                "error": "page text must never appear here",
            })

        with self.assertRaisesRegex(ClientError, "non-generic error"):
            self.run_server(program, handler)

    def test_result_shape_and_public_counters_are_exact(self) -> None:
        program = fixture("x-space-read-v1.json")

        def extra_field(connection: socket.socket, job: dict) -> None:
            send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": "result",
                "job_id": job["job_id"],
                "status": "ok",
                "public": {"status": "ok"},
                "private": {},
                "undeclared": "synthetic",
            })

        with self.assertRaisesRegex(ClientError, "result shape"):
            self.run_server(program, extra_field)

        def wrong_count(connection: socket.socket, job: dict) -> None:
            send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": "result",
                "job_id": job["job_id"],
                "status": "ok",
                "public": {"status": "ok", "private_result_count": 2},
                "private": {},
            })

        with self.assertRaisesRegex(ClientError, "private result count"):
            self.run_server(program, wrong_count)

    def test_private_values_must_exactly_match_slots(self) -> None:
        program = fixture("google-docs-suggestions-v1.json")
        with self.assertRaisesRegex(ProtocolError, "exactly match"):
            BrowserExecutorClient(Path("/tmp/absent-executor.sock")).run(
                program,
                private_values={"edit.find": "synthetic"},
                before_mutation=lambda: None,
            )

    def test_private_values_are_individually_bounded(self) -> None:
        program = fixture("google-docs-suggestions-v1.json")
        with self.assertRaisesRegex(ProtocolError, "oversized"):
            BrowserExecutorClient(Path("/tmp/absent-executor.sock")).run(
                program,
                private_values={"edit.find": "x" * 16_385, "edit.replace": "synthetic"},
                before_mutation=lambda: None,
            )


if __name__ == "__main__":
    unittest.main()
