from __future__ import annotations

import json
import os
import re
import socket
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

from .protocol import BROWSER_PROTOCOL, ProtocolError, validate_program
from .storage import (
    StorageError,
    native_socket_candidates,
    native_socket_path,
    validate_private_socket,
)

MAX_MESSAGE_BYTES = 1_048_576
MAX_PRIVATE_VALUE_BYTES = 16_384
MAX_PRIVATE_VALUES_BYTES = 262_144
ERROR_CODE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
COLLABORATION_ID = re.compile(r"^[a-f0-9]{64}$")
RESULT_KEYS = {"protocol", "type", "job_id", "status", "public", "private", "error"}


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
    if any(len(value.encode("utf-8")) > MAX_PRIVATE_VALUE_BYTES for value in values.values()):
        raise ProtocolError("private_values contains an oversized value")
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > MAX_PRIVATE_VALUES_BYTES:
        raise ProtocolError("private_values is too large")
    return dict(values)


def _validate_result(
    message: dict[str, Any],
    job_id: str,
    program: dict[str, Any],
    authorized: bool,
) -> dict[str, Any]:
    result_shape = frozenset(message)
    if result_shape not in {frozenset(RESULT_KEYS), frozenset(RESULT_KEYS - {"error"})}:
        raise ClientError("browser executor returned an invalid result shape")
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
    if status == "ok" and "error" in message:
        raise ClientError("browser executor returned an error with success")
    if status == "error" and (not isinstance(error, str) or not ERROR_CODE.fullmatch(error)):
        raise ClientError("browser executor returned a non-generic error")
    if "status" in public and public["status"] != status:
        raise ClientError("browser executor public status does not match")
    if "action_count" in public and (
        type(public["action_count"]) is not int
        or not 0 <= public["action_count"] <= program["limits"]["max_actions"]
    ):
        raise ClientError("browser executor returned an invalid action count")
    if "mutation_started" in public and not isinstance(public["mutation_started"], bool):
        raise ClientError("browser executor returned an invalid mutation state")
    if "private_result_count" in public and (
        type(public["private_result_count"]) is not int
        or public["private_result_count"] != len(private)
    ):
        raise ClientError("browser executor returned an invalid private result count")
    return {"status": status, "public": public, "private": private, **({"error": error} if error else {})}


class BrowserExecutorClient:
    """Send one exact-target typed job through the private native connector."""

    def __init__(self, socket_path: Path | None = None, timeout_seconds: int = 300) -> None:
        self.socket_path = (socket_path or native_socket_path()).resolve(strict=False)
        self.timeout_seconds = max(10, min(timeout_seconds, 300))

    def _connector_candidates(self) -> list[Path]:
        candidates = native_socket_candidates(self.socket_path)
        private = []
        for candidate in candidates:
            try:
                validate_private_socket(candidate)
            except StorageError:
                continue
            private.append(candidate)
        if not private:
            raise ClientError("browser executor connector is offline or not private")
        return private

    def _query_connector(self, message_type: str, socket_path: Path) -> dict[str, Any]:
        try:
            validate_private_socket(socket_path)
        except StorageError as exc:
            raise ClientError("browser executor connector is offline or not private") from exc
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(min(5.0, float(self.timeout_seconds)))
        try:
            try:
                connection.connect(str(socket_path))
            except OSError as exc:
                raise ClientError("browser executor connector is unavailable") from exc
            _send_line(connection, {
                "protocol": BROWSER_PROTOCOL,
                "type": message_type,
            })
            return _receive_line(connection, bytearray())
        finally:
            connection.close()

    @staticmethod
    def _validate_collaboration(value: Any) -> dict[str, str]:
        if not isinstance(value, dict) or set(value) != {"collaboration_id", "url", "origin"}:
            raise ClientError("browser executor returned invalid collaboration state")
        collaboration_id = value.get("collaboration_id")
        raw_url = value.get("url")
        raw_origin = value.get("origin")
        if (
            not isinstance(collaboration_id, str)
            or not COLLABORATION_ID.fullmatch(collaboration_id)
            or not isinstance(raw_url, str)
            or not isinstance(raw_origin, str)
            or len(raw_url.encode("utf-8")) > MAX_PRIVATE_VALUE_BYTES
        ):
            raise ClientError("browser executor returned invalid collaboration state")
        url = urlsplit(raw_url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or raw_origin != f"{url.scheme}://{url.netloc}"
        ):
            raise ClientError("browser executor returned invalid collaboration state")
        return {
            "collaboration_id": collaboration_id,
            "url": raw_url,
            "origin": raw_origin,
        }

    def _validate_collaboration_workspace(self, message: dict[str, Any]) -> dict[str, Any]:
        if set(message) != {
            "protocol", "type", "selected_collaboration_id", "collaborations",
        } or message.get("type") != "collaboration-list":
            raise ClientError("browser executor returned invalid collaboration workspace")
        raw_collaborations = message.get("collaborations")
        if not isinstance(raw_collaborations, list) or len(raw_collaborations) > 16:
            raise ClientError("browser executor returned invalid collaboration workspace")
        collaborations = [self._validate_collaboration(value) for value in raw_collaborations]
        identifiers = {value["collaboration_id"] for value in collaborations}
        urls = {value["url"] for value in collaborations}
        if len(identifiers) != len(collaborations) or len(urls) != len(collaborations):
            raise ClientError("browser executor returned duplicate collaboration targets")
        selected = message.get("selected_collaboration_id")
        if selected is not None and (
            not isinstance(selected, str)
            or not COLLABORATION_ID.fullmatch(selected)
            or selected not in identifiers
        ):
            raise ClientError("browser executor returned invalid selected collaboration")
        return {
            "selected_collaboration_id": selected,
            "collaborations": collaborations,
        }

    def _collaboration_workspaces(self) -> list[tuple[Path, dict[str, Any]]]:
        workspaces = []
        for candidate in self._connector_candidates():
            try:
                message = self._query_connector("collaboration-list-query", candidate)
                workspace = self._validate_collaboration_workspace(message)
            except ClientError:
                continue
            workspaces.append((candidate, workspace))
        if not workspaces:
            raise ClientError("browser executor connector is unavailable")
        identifiers = [
            collaboration["collaboration_id"]
            for _path, workspace in workspaces
            for collaboration in workspace["collaborations"]
        ]
        if len(identifiers) != len(set(identifiers)):
            raise ClientError("browser executor returned duplicate collaboration targets")
        return workspaces

    def collaborations(self) -> list[dict[str, str]]:
        """Return every exact HTTPS tab the user explicitly shared."""
        collaborations = []
        for path, workspace in self._collaboration_workspaces():
            selected = workspace["selected_collaboration_id"]
            for value in workspace["collaborations"]:
                collaborations.append((
                    value["collaboration_id"] != selected,
                    str(path),
                    value,
                ))
        return [
            value for _not_selected, _path, value in sorted(
                collaborations,
                key=lambda item: (item[0], item[1], item[2]["collaboration_id"]),
            )
        ]

    def collaboration_for_url(self, raw_url: str) -> dict[str, str] | None:
        """Return the unique explicit grant for an exact HTTPS URL."""
        if not isinstance(raw_url, str) or len(raw_url.encode("utf-8")) > MAX_PRIVATE_VALUE_BYTES:
            raise ClientError("collaboration URL is invalid")
        url = urlsplit(raw_url)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
        ):
            raise ClientError("collaboration URL is invalid")
        matches = [value for value in self.collaborations() if value["url"] == raw_url]
        if len(matches) > 1:
            raise ClientError("browser executor returned an ambiguous collaboration target")
        return matches[0] if matches else None

    def current_collaboration(self) -> dict[str, str] | None:
        """Return the most recently selected explicit tab, preserving the v1 client API."""
        for _path, workspace in self._collaboration_workspaces():
            selected = workspace["selected_collaboration_id"]
            value = next((
                value for value in workspace["collaborations"]
                if value["collaboration_id"] == selected
            ), None)
            if value is not None:
                return value
        return None

    def _connector_for_program(self, program: dict[str, Any]) -> Path:
        candidates = self._connector_candidates()
        if len(candidates) == 1:
            return candidates[0]
        target = program["target"]
        matches = []
        for candidate, workspace in self._collaboration_workspaces():
            if any(
                value["collaboration_id"] == target["collaboration_id"]
                and value["url"] == target["url"]
                and value["origin"] == target["origin"]
                for value in workspace["collaborations"]
            ):
                matches.append(candidate)
        if len(matches) != 1:
            raise ClientError("the exact clicked-tab grant is unavailable or ambiguous")
        return matches[0]

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
        connector_path = self._connector_for_program(validated)
        try:
            validate_private_socket(connector_path)
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
                connection.connect(str(connector_path))
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
                    if set(message) != {"protocol", "type", "job_id"}:
                        raise ClientError("browser executor returned an invalid mutation boundary")
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
