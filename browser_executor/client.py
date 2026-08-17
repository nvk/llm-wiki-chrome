from __future__ import annotations

import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any, Callable

from .protocol import BROWSER_PROTOCOL, ProtocolError, validate_program
from .storage import StorageError, native_socket_path, validate_private_socket

MAX_MESSAGE_BYTES = 1_048_576
ERROR_CODE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")


class ClientError(RuntimeError):
    """Raised when the local browser executor cannot complete a bounded job."""


def _send_line(connection: socket.socket, value: dict[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_BYTES:
        raise ClientError("browser executor message is too large")
    connection.sendall(payload + b"\n")


def _receive_line(connection: socket.socket, buffer: bytearray) -> dict[str, Any]:
    while b"\n" not in buffer:
        chunk = connection.recv(65536)
        if not chunk:
            raise ClientError("browser executor disconnected before returning a result")
        buffer.extend(chunk)
        if len(buffer) > MAX_MESSAGE_BYTES:
            raise ClientError("browser executor message is too large")
    line, _, remainder = bytes(buffer).partition(b"\n")
    buffer.clear()
    buffer.extend(remainder)
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ClientError("browser executor returned invalid JSON") from exc
    if not isinstance(value, dict) or value.get("protocol") != BROWSER_PROTOCOL:
        raise ClientError("browser executor protocol does not match the client")
    return value


def _validate_private_values(program: dict[str, Any], values: Any) -> dict[str, str]:
    if values is None:
        values = {}
    if not isinstance(values, dict):
        raise ProtocolError("private_values must be an object")
    expected = set(program.get("private_slots", []))
    if set(values) != expected:
        raise ProtocolError("private_values do not exactly match declared private slots")
    if not all(isinstance(value, str) for value in values.values()):
        raise ProtocolError("private_values must contain strings")
    return dict(values)


def _validate_result(
    message: dict[str, Any],
    job_id: str,
    program: dict[str, Any],
    authorized: bool,
) -> dict[str, Any]:
    if message.get("type") != "result" or message.get("job_id") != job_id:
        raise ClientError("browser executor returned a result for another job")
    status = message.get("status")
    if status not in {"ok", "error"}:
        raise ClientError("browser executor returned an invalid status")
    public = message.get("public", {})
    private = message.get("private", {})
    if not isinstance(public, dict) or not isinstance(private, dict):
        raise ClientError("browser executor result fields must be objects")
    permitted_public = set(program["result"].get("public_fields", []))
    if not set(public).issubset(permitted_public):
        raise ClientError("browser executor returned an undeclared public field")
    permitted_private = set(program["result"].get("private_fields", []))
    if not set(private).issubset(permitted_private):
        raise ClientError("browser executor returned an undeclared private field")
    if status == "ok" and program["capability"] == "mutation" and not authorized:
        raise ClientError("browser executor reported mutation success without authorization")
    error = message.get("error")
    if error is not None and (not isinstance(error, str) or not ERROR_CODE.fullmatch(error)):
        raise ClientError("browser executor returned a non-generic error")
    return {"status": status, "public": public, "private": private, **({"error": error} if error else {})}


class BrowserExecutorClient:
    """Send one exact-target typed job through the private native connector."""

    def __init__(self, socket_path: Path | None = None, timeout_seconds: int = 300) -> None:
        self.socket_path = (socket_path or native_socket_path()).resolve(strict=False)
        self.timeout_seconds = max(10, min(timeout_seconds, 300))

    def run(
        self,
        program: dict[str, Any],
        *,
        private_values: dict[str, str] | None = None,
        before_mutation: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        validated = validate_program(program)
        values = _validate_private_values(validated, private_values)
        if validated["capability"] == "mutation" and before_mutation is None:
            raise ProtocolError("mutation jobs require a before_mutation callback")
        try:
            validate_private_socket(self.socket_path)
        except StorageError as exc:
            raise ClientError("browser executor connector is offline or not private") from exc
        job_id = os.urandom(18).hex()
        job = {
            "protocol": BROWSER_PROTOCOL,
            "type": "job",
            "job_id": job_id,
            "program": validated,
            "private_values": values,
        }
        authorized = False
        deadline = time.monotonic() + self.timeout_seconds
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(min(5.0, float(self.timeout_seconds)))
        try:
            try:
                connection.connect(str(self.socket_path))
            except OSError as exc:
                raise ClientError("browser executor connector is unavailable") from exc
            _send_line(connection, job)
            buffer = bytearray()
            while time.monotonic() < deadline:
                connection.settimeout(max(0.1, deadline - time.monotonic()))
                try:
                    message = _receive_line(connection, buffer)
                except socket.timeout as exc:
                    raise ClientError("timed out waiting for the browser executor") from exc
                if message.get("type") == "before-mutation":
                    if validated["capability"] != "mutation" or message.get("job_id") != job_id:
                        raise ClientError("browser executor returned an unexpected mutation boundary")
                    if authorized:
                        raise ClientError("browser executor repeated the mutation boundary")
                    assert before_mutation is not None
                    try:
                        before_mutation()
                    except Exception:
                        _send_line(connection, {
                            "protocol": BROWSER_PROTOCOL,
                            "type": "mutation-authorized",
                            "job_id": job_id,
                            "authorized": False,
                        })
                        raise
                    authorized = True
                    _send_line(connection, {
                        "protocol": BROWSER_PROTOCOL,
                        "type": "mutation-authorized",
                        "job_id": job_id,
                        "authorized": True,
                    })
                    continue
                return _validate_result(message, job_id, validated, authorized)
            raise ClientError("timed out waiting for the browser executor")
        finally:
            connection.close()
