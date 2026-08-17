from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Callable
from urllib.parse import urlsplit

from .client import BrowserExecutorClient, ClientError
from .protocol import BROWSER_PROTOCOL, canonical_program_sha256, validate_program

DRIVER_ID = "agent-collaboration"
DRIVER_VERSION = "1"
COLLABORATION_ID = re.compile(r"^[a-f0-9]{64}$")
ROLE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SAFE_REGEX_FORBIDDEN = re.compile(r"(?:[+*?]){2,}|\\(?:[1-9]|k[<{])")
LOCATOR_KEYS = {
    "role",
    "roles",
    "name",
    "name_contains",
    "name_contains_any",
    "name_matches",
    "within",
    "within_name_contains_any",
    "ordinal",
    "checked",
    "focused",
    "unique",
}
KEY_NAMES = {
    "platform-primary",
    "control",
    "meta",
    "alt",
    "shift",
    "enter",
    "escape",
    "tab",
    "arrow-up",
    "arrow-down",
    "arrow-left",
    "arrow-right",
    "backspace",
    "delete",
    *tuple("abcdefghijklmnopqrstuvwxyz"),
    *tuple("0123456789"),
}


class CollaborationError(RuntimeError):
    """Raised when a direct collaboration request exceeds its explicit grant."""


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _bounded_text(value: Any, name: str, *, maximum: int = 16_384) -> str:
    if not isinstance(value, str) or not value:
        raise CollaborationError(f"{name} must be a non-empty string")
    if len(value.encode("utf-8")) > maximum:
        raise CollaborationError(f"{name} is too large")
    return value


def _validate_locator(value: Any, *, depth: int = 0) -> dict[str, Any]:
    if depth > 2 or not isinstance(value, dict) or not value:
        raise CollaborationError("locator must be a bounded semantic object")
    if set(value).difference(LOCATOR_KEYS):
        raise CollaborationError("locator contains unsupported fields")
    if not {
        "role", "roles", "name", "name_contains", "name_contains_any", "name_matches",
        "within", "within_name_contains_any",
    }.intersection(value):
        raise CollaborationError("locator needs a semantic identity predicate")
    result: dict[str, Any] = {}
    if "role" in value:
        role = _bounded_text(value["role"], "locator.role", maximum=64)
        if not ROLE.fullmatch(role):
            raise CollaborationError("locator.role is invalid")
        result["role"] = role
    if "roles" in value:
        roles = value["roles"]
        if (
            not isinstance(roles, list)
            or not 1 <= len(roles) <= 8
            or len(roles) != len(set(roles))
            or not all(isinstance(role, str) and ROLE.fullmatch(role) for role in roles)
        ):
            raise CollaborationError("locator.roles is invalid")
        result["roles"] = list(roles)
    for key in ("name", "name_contains"):
        if key in value:
            result[key] = _bounded_text(value[key], f"locator.{key}", maximum=512)
    if "name_matches" in value:
        pattern = _bounded_text(value["name_matches"], "locator.name_matches", maximum=256)
        if any(token in pattern for token in ("(", ")", "{", "}")) or SAFE_REGEX_FORBIDDEN.search(pattern):
            raise CollaborationError("locator.name_matches is outside the safe regex subset")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise CollaborationError("locator.name_matches is invalid") from exc
        result["name_matches"] = pattern
    for key in ("name_contains_any", "within_name_contains_any"):
        if key in value:
            items = value[key]
            if (
                not isinstance(items, list)
                or not 1 <= len(items) <= 12
                or not all(
                    isinstance(item, str)
                    and item
                    and len(item.encode("utf-8")) <= 512
                    for item in items
                )
            ):
                raise CollaborationError(f"locator.{key} is invalid")
            result[key] = list(items)
    if "within" in value:
        result["within"] = _validate_locator(value["within"], depth=depth + 1)
    if "ordinal" in value:
        ordinal = value["ordinal"]
        if type(ordinal) is not int or not 0 <= ordinal <= 1000:
            raise CollaborationError("locator.ordinal is out of bounds")
        result["ordinal"] = ordinal
    for key in ("checked", "focused", "unique"):
        if key in value:
            if not isinstance(value[key], bool):
                raise CollaborationError(f"locator.{key} must be boolean")
            result[key] = value[key]
    return result


def _target(collaboration: dict[str, str]) -> dict[str, Any]:
    raw_url = collaboration["url"]
    parsed = urlsplit(raw_url)
    return {
        "url": raw_url,
        "origin": collaboration["origin"],
        "path_prefixes": [parsed.path or "/"],
        "collaboration_id": collaboration["collaboration_id"],
    }


def _program(
    collaboration: dict[str, str],
    operation: str,
    actions: list[dict[str, Any]],
    *,
    capability: str = "read",
    private_slots: list[str] | None = None,
    private_fields: list[str] | None = None,
    timeout_ms: int = 30_000,
    max_repeat: int = 5,
    intent: Any = None,
) -> dict[str, Any]:
    target = _target(collaboration)
    plan_sha256 = _canonical_hash({
        "driver": DRIVER_ID,
        "operation": operation,
        "target": target,
        "intent": intent,
    })
    value = {
        "protocol": BROWSER_PROTOCOL,
        "program_id": f"agent-{operation}-{plan_sha256[:16]}",
        "plan_sha256": plan_sha256,
        "driver": {"id": DRIVER_ID, "version": DRIVER_VERSION},
        "capability": capability,
        "target": target,
        "limits": {
            "timeout_ms": timeout_ms,
            "max_actions": max(8, len(actions) + 2),
            "max_repeat": max_repeat,
        },
        "private_slots": private_slots or [],
        "actions": actions,
        "result": {
            "public_fields": [
                "status", "action_count", "mutation_started", "private_result_count",
            ],
            "private_fields": private_fields or [],
        },
    }
    value["program_sha256"] = canonical_program_sha256(value)
    return validate_program(value)


class BrowserCollaborationController:
    """Compile fixed agent tools into exact-tab executor programs."""

    def __init__(
        self,
        client: BrowserExecutorClient | None = None,
        authorize_mutation: Callable[[], None] | None = None,
    ) -> None:
        self.client = client or BrowserExecutorClient()
        self.authorize_mutation = authorize_mutation or (lambda: None)

    def tabs(self) -> list[dict[str, str]]:
        """Return only tabs explicitly shared by clicking the extension action."""
        return self.client.collaborations()

    def status(self) -> dict[str, Any]:
        """Return content-free connector and click-grant readiness."""
        collaborations = self.client.collaborations()
        return {
            "connected": True,
            "shared_tabs": len(collaborations),
            "ready": bool(collaborations),
        }

    def _collaboration(self, collaboration_id: Any) -> dict[str, str]:
        if not isinstance(collaboration_id, str) or not COLLABORATION_ID.fullmatch(collaboration_id):
            raise CollaborationError("collaboration_id is invalid")
        matches = [
            value for value in self.client.collaborations()
            if value["collaboration_id"] == collaboration_id
        ]
        if len(matches) != 1:
            raise CollaborationError("that clicked-tab grant is no longer active")
        return matches[0]

    def snapshot(self, collaboration_id: str, *, max_items: int = 400) -> dict[str, Any]:
        if type(max_items) is not int or not 1 <= max_items <= 1500:
            raise CollaborationError("max_items must be between 1 and 1500")
        collaboration = self._collaboration(collaboration_id)
        locator = {"name_matches": ".+"}
        fields = ["role", "name", "value", "description", "url", "checked", "focused"]
        program = _program(
            collaboration,
            "snapshot",
            [
                {"op": "open_or_focus_exact_url"},
                {"op": "assert_exact_target"},
                {"op": "attach_debugger"},
                {
                    "op": "extract_ax_collection",
                    "locator": locator,
                    "fields": fields,
                    "private_result": "page.ax",
                    "max_items": max_items,
                },
                {"op": "detach_debugger"},
            ],
            private_fields=["page.ax"],
            intent={"max_items": max_items, "fields": fields},
        )
        result = self.client.run(program)
        self._require_ok(result)
        return {
            "collaboration_id": collaboration_id,
            "url": collaboration["url"],
            "nodes": result["private"]["page.ax"],
        }

    def screenshot(
        self,
        collaboration_id: str,
        *,
        quality: int = 65,
        max_bytes: int = 262_144,
    ) -> dict[str, Any]:
        if type(quality) is not int or not 10 <= quality <= 90:
            raise CollaborationError("quality must be between 10 and 90")
        if type(max_bytes) is not int or not 16_384 <= max_bytes <= 262_144:
            raise CollaborationError("max_bytes must be between 16384 and 262144")
        collaboration = self._collaboration(collaboration_id)
        program = _program(
            collaboration,
            "screenshot",
            [
                {"op": "open_or_focus_exact_url"},
                {"op": "assert_exact_target"},
                {"op": "attach_debugger"},
                {
                    "op": "capture_viewport_private",
                    "private_result": "page.viewport",
                    "quality": quality,
                    "max_bytes": max_bytes,
                },
                {"op": "detach_debugger"},
            ],
            private_fields=["page.viewport"],
            intent={"quality": quality, "max_bytes": max_bytes},
        )
        result = self.client.run(program)
        self._require_ok(result)
        capture = result["private"]["page.viewport"]
        return {
            "collaboration_id": collaboration_id,
            "url": collaboration["url"],
            "mime_type": capture["mime_type"],
            "data_base64": capture["data_base64"],
        }

    def click(self, collaboration_id: str, locator: Any) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        program = _program(
            collaboration,
            "click",
            [
                {"op": "open_or_focus_exact_url"},
                {"op": "assert_exact_target"},
                {"op": "attach_debugger"},
                {"op": "assert_ax", "locator": semantic_locator},
                {"op": "before_mutation"},
                {"op": "click_ax", "locator": semantic_locator},
                {"op": "detach_debugger"},
            ],
            capability="mutation",
            intent={"locator": semantic_locator},
        )
        result = self.client.run(program, before_mutation=self.authorize_mutation)
        self._require_ok(result)
        return self._mutation_receipt(collaboration_id, result)

    def type_text(
        self,
        collaboration_id: str,
        locator: Any,
        text: Any,
        *,
        replace_all: bool = True,
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        private_text = _bounded_text(text, "text")
        if not isinstance(replace_all, bool):
            raise CollaborationError("replace_all must be boolean")
        program = _program(
            collaboration,
            "type",
            [
                {"op": "open_or_focus_exact_url"},
                {"op": "assert_exact_target"},
                {"op": "attach_debugger"},
                {"op": "assert_ax", "locator": semantic_locator},
                {"op": "focus_ax", "locator": semantic_locator},
                {"op": "before_mutation"},
                {"op": "insert_private_text", "slot": "input.text", "replace_all": replace_all},
                {"op": "assert_ax_private_value", "slot": "input.text"},
                {"op": "detach_debugger"},
            ],
            capability="mutation",
            private_slots=["input.text"],
            intent={
                "locator": semantic_locator,
                "text_sha256": hashlib.sha256(private_text.encode("utf-8")).hexdigest(),
                "replace_all": replace_all,
            },
        )
        result = self.client.run(
            program,
            private_values={"input.text": private_text},
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        return self._mutation_receipt(collaboration_id, result)

    def key_chord(self, collaboration_id: str, keys: Any) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        if (
            not isinstance(keys, list)
            or not 1 <= len(keys) <= 5
            or len(keys) != len(set(keys))
            or not all(isinstance(key, str) and key in KEY_NAMES for key in keys)
        ):
            raise CollaborationError("keys must be one bounded supported key chord")
        program = _program(
            collaboration,
            "key",
            [
                {"op": "open_or_focus_exact_url"},
                {"op": "assert_exact_target"},
                {"op": "attach_debugger"},
                {"op": "before_mutation"},
                {"op": "dispatch_key_chord", "keys": list(keys)},
                {"op": "detach_debugger"},
            ],
            capability="mutation",
            intent={"keys": list(keys)},
        )
        result = self.client.run(program, before_mutation=self.authorize_mutation)
        self._require_ok(result)
        return self._mutation_receipt(collaboration_id, result)

    def scroll(
        self,
        collaboration_id: str,
        *,
        direction: str,
        distance_px: int = 700,
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        if direction not in {"up", "down"}:
            raise CollaborationError("direction must be up or down")
        if type(distance_px) is not int or not 1 <= distance_px <= 10_000:
            raise CollaborationError("distance_px must be between 1 and 10000")
        program = _program(
            collaboration,
            "scroll",
            [
                {"op": "open_or_focus_exact_url"},
                {"op": "assert_exact_target"},
                {"op": "attach_debugger"},
                {"op": "scroll_viewport", "direction": direction, "distance_px": distance_px},
                {"op": "detach_debugger"},
            ],
            intent={"direction": direction, "distance_px": distance_px},
        )
        result = self.client.run(program)
        self._require_ok(result)
        return {
            "status": "ok",
            "collaboration_id": collaboration_id,
            "action_count": result["public"].get("action_count", 0),
        }

    @staticmethod
    def _require_ok(result: dict[str, Any]) -> None:
        if result.get("status") != "ok":
            code = result.get("error", "browser-operation-failed")
            raise CollaborationError(f"browser executor failed: {code}")

    @staticmethod
    def _mutation_receipt(collaboration_id: str, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ok",
            "collaboration_id": collaboration_id,
            "action_count": result["public"].get("action_count", 0),
            "mutation_started": result["public"].get("mutation_started", False),
        }


def collaboration_error_message(exc: BaseException) -> str:
    if isinstance(exc, (CollaborationError, ClientError)):
        return str(exc)
    return "browser collaboration failed"
