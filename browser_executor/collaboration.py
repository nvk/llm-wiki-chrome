from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from typing import Any, Callable
from urllib.parse import urlsplit

from .client import BrowserExecutorClient, ClientError
from .protocol import BROWSER_PROTOCOL, canonical_program_sha256, validate_program
from .policy import LocalBrowserPolicy, PolicyError

MAX_ACTIVE_SCHEDULES = 4
MAX_RETAINED_SCHEDULES = 32

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


def _file_sha256(path: Any) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        "role",
        "roles",
        "name",
        "name_contains",
        "name_contains_any",
        "name_matches",
        "within",
        "within_name_contains_any",
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
        pattern = _bounded_text(
            value["name_matches"], "locator.name_matches", maximum=256
        )
        if any(
            token in pattern for token in ("(", ")", "{", "}")
        ) or SAFE_REGEX_FORBIDDEN.search(pattern):
            raise CollaborationError(
                "locator.name_matches is outside the safe regex subset"
            )
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
                    isinstance(item, str) and item and len(item.encode("utf-8")) <= 512
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
    return {
        "url": raw_url,
        "origin": collaboration["origin"],
        "path_prefixes": ["/"],
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
    plan_sha256 = _canonical_hash(
        {
            "driver": DRIVER_ID,
            "operation": operation,
            "target": target,
            "intent": intent,
        }
    )
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
                "status",
                "action_count",
                "mutation_started",
                "private_result_count",
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
        policy: LocalBrowserPolicy | None = None,
    ) -> None:
        self.client = client or BrowserExecutorClient()
        self.authorize_mutation = authorize_mutation or (lambda: None)
        self.policy = policy or LocalBrowserPolicy.load()
        self._recording: dict[str, Any] | None = None
        self._schedule_lock = threading.Lock()
        self._schedules: dict[str, dict[str, Any]] = {}

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
        if not isinstance(collaboration_id, str) or not COLLABORATION_ID.fullmatch(
            collaboration_id
        ):
            raise CollaborationError("collaboration_id is invalid")
        matches = [
            value
            for value in self.client.collaborations()
            if value["collaboration_id"] == collaboration_id
        ]
        if len(matches) != 1:
            raise CollaborationError("that clicked-tab grant is no longer active")
        return matches[0]

    def _collaboration_for_url(self, url: str) -> dict[str, str]:
        for _attempt in range(20):
            value = self.client.collaboration_for_url(url)
            if value is not None:
                return value
            time.sleep(0.05)
        raise CollaborationError("the updated exact-tab grant was not published")

    def focus(self, collaboration_id: str) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        result = self.client.run(
            _program(
                collaboration,
                "focus",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "detach_debugger"},
                ],
                intent={"focus": True},
            )
        )
        self._require_ok(result)
        return {"status": "ok", "collaboration_id": collaboration_id}

    def open(self, collaboration_id: str, url: Any) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        target = _bounded_text(url, "url")
        desired = urlsplit(target)
        if (
            desired.scheme != "https"
            or desired.username is not None
            or desired.password is not None
            or desired.fragment
            or f"{desired.scheme}://{desired.netloc}" != collaboration["origin"]
        ):
            raise CollaborationError(
                "url must be an exact same-origin HTTPS URL without a fragment"
            )
        result = self.client.run(
            _program(
                collaboration,
                "open",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "before_mutation"},
                    {"op": "create_same_origin_tab", "url": target},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "detach_debugger"},
                ],
                capability="mutation",
                intent={"url_sha256": hashlib.sha256(target.encode()).hexdigest()},
            ),
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        created = self._collaboration_for_url(target)
        self._record("open", {"url": target})
        return {"status": "ok", "tab": created}

    def history(
        self,
        collaboration_id: str,
        *,
        direction: str,
        expected_url: Any,
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        if direction not in {"back", "forward"}:
            raise CollaborationError("direction must be back or forward")
        target = _bounded_text(expected_url, "expected_url")
        desired = urlsplit(target)
        if (
            desired.scheme != "https"
            or desired.username is not None
            or desired.password is not None
            or desired.fragment
            or f"{desired.scheme}://{desired.netloc}" != collaboration["origin"]
        ):
            raise CollaborationError(
                "expected_url must be an exact same-origin HTTPS URL"
            )
        result = self.client.run(
            _program(
                collaboration,
                "history",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "before_mutation"},
                    {
                        "op": "navigate_history",
                        "direction": direction,
                        "expected_url": target,
                    },
                    {"op": "detach_debugger"},
                ],
                capability="mutation",
                intent={
                    "direction": direction,
                    "expected_url_sha256": hashlib.sha256(target.encode()).hexdigest(),
                },
            ),
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        self._record("history", {"direction": direction, "expected_url": target})
        receipt = self._mutation_receipt(collaboration_id, result)
        receipt["tab"] = self._collaboration_for_url(target)
        return receipt

    def close(self, collaboration_id: str) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        result = self.client.run(
            _program(
                collaboration,
                "close",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "before_mutation"},
                    {"op": "detach_debugger"},
                    {"op": "close_target_tab"},
                ],
                capability="mutation",
                intent={"close": True},
            ),
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        self._record("close", {})
        return self._mutation_receipt(collaboration_id, result)

    def snapshot(
        self, collaboration_id: str, *, max_items: int = 400
    ) -> dict[str, Any]:
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

    def wait(
        self,
        collaboration_id: str,
        locator: Any,
        *,
        timeout_ms: int = 10_000,
    ) -> dict[str, Any]:
        if type(timeout_ms) is not int or not 50 <= timeout_ms <= 300_000:
            raise CollaborationError("timeout_ms must be between 50 and 300000")
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        actions = [
            {"op": "open_or_focus_exact_url"},
            {"op": "assert_exact_target"},
            {"op": "attach_debugger"},
            {"op": "wait_ax", "locator": semantic_locator, "timeout_ms": timeout_ms},
            {"op": "detach_debugger"},
        ]
        result = self.client.run(
            _program(
                collaboration,
                "wait",
                actions,
                timeout_ms=max(1000, timeout_ms),
                intent={"locator": semantic_locator, "timeout_ms": timeout_ms},
            )
        )
        self._require_ok(result)
        self._record("wait", {"locator": semantic_locator, "timeout_ms": timeout_ms})
        return {"status": "ok", "collaboration_id": collaboration_id}

    def navigate(
        self, collaboration_id: str, url: Any, *, ignore_cache: bool = False
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        target = _bounded_text(url, "url")
        current = urlsplit(collaboration["url"])
        desired = urlsplit(target)
        if (
            desired.scheme != "https"
            or desired.username is not None
            or desired.password is not None
            or desired.fragment
            or f"{desired.scheme}://{desired.netloc}" != collaboration["origin"]
        ):
            raise CollaborationError(
                "url must be an exact same-origin HTTPS URL without a fragment"
            )
        if not isinstance(ignore_cache, bool):
            raise CollaborationError("ignore_cache must be boolean")
        actions = [
            {"op": "open_or_focus_exact_url"},
            {"op": "assert_exact_target"},
            {"op": "attach_debugger"},
            {"op": "before_mutation"},
            {"op": "navigate_same_origin", "url": target},
            *(
                [{"op": "reload_exact_target", "ignore_cache": True}]
                if ignore_cache
                else []
            ),
            {"op": "detach_debugger"},
        ]
        result = self.client.run(
            _program(
                collaboration,
                "navigate",
                actions,
                capability="mutation",
                intent={
                    "url_sha256": hashlib.sha256(target.encode()).hexdigest(),
                    "ignore_cache": ignore_cache,
                    "from_path": current.path,
                },
            ),
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        self._record("navigate", {"url": target, "ignore_cache": ignore_cache})
        receipt = self._mutation_receipt(collaboration_id, result)
        receipt["tab"] = self._collaboration_for_url(target)
        return receipt

    def reload(
        self, collaboration_id: str, *, ignore_cache: bool = False
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        if not isinstance(ignore_cache, bool):
            raise CollaborationError("ignore_cache must be boolean")
        actions = [
            {"op": "open_or_focus_exact_url"},
            {"op": "assert_exact_target"},
            {"op": "attach_debugger"},
            {"op": "reload_exact_target", "ignore_cache": ignore_cache},
            {"op": "detach_debugger"},
        ]
        result = self.client.run(
            _program(
                collaboration,
                "reload",
                actions,
                intent={"ignore_cache": ignore_cache},
            )
        )
        self._require_ok(result)
        self._record("reload", {"ignore_cache": ignore_cache})
        return {"status": "ok", "collaboration_id": collaboration_id}

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

    def region_screenshot(
        self,
        collaboration_id: str,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        quality: int = 65,
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        for name, value, lower, upper in (
            ("x", x, 0, 100000),
            ("y", y, 0, 100000),
            ("width", width, 1, 10000),
            ("height", height, 1, 10000),
        ):
            if type(value) not in {int, float} or not lower <= value <= upper:
                raise CollaborationError(f"{name} is out of bounds")
        if type(quality) is not int or not 10 <= quality <= 90:
            raise CollaborationError("quality must be between 10 and 90")
        action = {
            "op": "capture_region_private",
            "private_result": "page.region",
            "quality": quality,
            "max_bytes": 262_144,
            "x": x,
            "y": y,
            "width": width,
            "height": height,
        }
        result = self.client.run(
            _program(
                collaboration,
                "region-screenshot",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    action,
                    {"op": "detach_debugger"},
                ],
                private_fields=["page.region"],
                intent={
                    key: action[key] for key in ("x", "y", "width", "height", "quality")
                },
            )
        )
        self._require_ok(result)
        capture = result["private"]["page.region"]
        return {
            "collaboration_id": collaboration_id,
            "url": collaboration["url"],
            **capture,
        }

    def full_page_screenshot(
        self, collaboration_id: str, *, quality: int = 60
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        if type(quality) is not int or not 10 <= quality <= 90:
            raise CollaborationError("quality must be between 10 and 90")
        action = {
            "op": "capture_full_page_private",
            "private_result": "page.full",
            "quality": quality,
            "max_bytes": 262_144,
            "max_width": 10000,
            "max_height": 20000,
        }
        result = self.client.run(
            _program(
                collaboration,
                "full-page-screenshot",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    action,
                    {"op": "detach_debugger"},
                ],
                private_fields=["page.full"],
                intent={"quality": quality},
            )
        )
        self._require_ok(result)
        capture = result["private"]["page.full"]
        return {
            "collaboration_id": collaboration_id,
            "url": collaboration["url"],
            **capture,
        }

    def geometry(
        self, collaboration_id: str, locator: Any, *, max_items: int = 100
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        if type(max_items) is not int or not 1 <= max_items <= 500:
            raise CollaborationError("max_items must be between 1 and 500")
        result = self.client.run(
            _program(
                collaboration,
                "geometry",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {
                        "op": "extract_ax_geometry",
                        "locator": semantic_locator,
                        "private_result": "page.geometry",
                        "max_items": max_items,
                    },
                    {"op": "detach_debugger"},
                ],
                private_fields=["page.geometry"],
                intent={"locator": semantic_locator, "max_items": max_items},
            )
        )
        self._require_ok(result)
        return {
            "collaboration_id": collaboration_id,
            "items": result["private"]["page.geometry"],
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
        self._record("click", {"locator": semantic_locator})
        return self._mutation_receipt(collaboration_id, result)

    def hover(self, collaboration_id: str, locator: Any) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        result = self.client.run(
            _program(
                collaboration,
                "hover",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "hover_ax", "locator": semantic_locator},
                    {"op": "detach_debugger"},
                ],
                intent={"locator": semantic_locator},
            )
        )
        self._require_ok(result)
        self._record("hover", {"locator": semantic_locator})
        return {"status": "ok", "collaboration_id": collaboration_id}

    def drag(
        self, collaboration_id: str, locator: Any, destination: Any, *, steps: int = 8
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        source = _validate_locator(locator)
        target = _validate_locator(destination)
        if type(steps) is not int or not 2 <= steps <= 50:
            raise CollaborationError("steps must be between 2 and 50")
        result = self.client.run(
            _program(
                collaboration,
                "drag",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "before_mutation"},
                    {
                        "op": "drag_ax",
                        "locator": source,
                        "destination": target,
                        "steps": steps,
                    },
                    {"op": "detach_debugger"},
                ],
                capability="mutation",
                intent={"locator": source, "destination": target, "steps": steps},
            ),
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        self._record("drag", {"locator": source, "destination": target, "steps": steps})
        return self._mutation_receipt(collaboration_id, result)

    def select(
        self, collaboration_id: str, locator: Any, option_locator: Any
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        target = _validate_locator(locator)
        option = _validate_locator(option_locator)
        result = self.client.run(
            _program(
                collaboration,
                "select",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "before_mutation"},
                    {
                        "op": "select_ax_option",
                        "locator": target,
                        "option_locator": option,
                    },
                    {"op": "detach_debugger"},
                ],
                capability="mutation",
                intent={"locator": target, "option_locator": option},
            ),
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        self._record("select", {"locator": target, "option_locator": option})
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
                {
                    "op": "insert_private_text",
                    "slot": "input.text",
                    "replace_all": replace_all,
                },
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
        self._record(
            "type",
            {
                "locator": semantic_locator,
                "replace_all": replace_all,
                "private_value_sha256": hashlib.sha256(
                    private_text.encode()
                ).hexdigest(),
            },
        )
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
        self._record("key", {"keys": list(keys)})
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
                {
                    "op": "scroll_viewport",
                    "direction": direction,
                    "distance_px": distance_px,
                },
                {"op": "detach_debugger"},
            ],
            intent={"direction": direction, "distance_px": distance_px},
        )
        result = self.client.run(program)
        self._require_ok(result)
        self._record("scroll", {"direction": direction, "distance_px": distance_px})
        return {
            "status": "ok",
            "collaboration_id": collaboration_id,
            "action_count": result["public"].get("action_count", 0),
        }

    def scroll_to(self, collaboration_id: str, locator: Any) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        result = self.client.run(
            _program(
                collaboration,
                "scroll-to",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "scroll_ax_into_view", "locator": semantic_locator},
                    {"op": "detach_debugger"},
                ],
                intent={"locator": semantic_locator},
            )
        )
        self._require_ok(result)
        self._record("scroll-to", {"locator": semantic_locator})
        return {"status": "ok", "collaboration_id": collaboration_id}

    def dialog(
        self,
        collaboration_id: str,
        *,
        accept: bool,
        prompt_text: Any = None,
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        if not isinstance(accept, bool):
            raise CollaborationError("accept must be boolean")
        if prompt_text is not None and (not accept or not isinstance(prompt_text, str)):
            raise CollaborationError("prompt_text is valid only for an accepted prompt")
        slots = ["dialog.prompt"] if prompt_text is not None else []
        private_values = (
            {"dialog.prompt": _bounded_text(prompt_text, "prompt_text")}
            if slots
            else None
        )
        result = self.client.run(
            _program(
                collaboration,
                "dialog",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "before_mutation"},
                    {
                        "op": "handle_dialog",
                        "accept": accept,
                        "prompt_slot": "dialog.prompt" if slots else None,
                    },
                    {"op": "detach_debugger"},
                ],
                capability="mutation",
                private_slots=slots,
                intent={"accept": accept, "has_prompt": bool(slots)},
            ),
            private_values=private_values,
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        self._record("dialog", {"accept": accept, "has_prompt": bool(slots)})
        return self._mutation_receipt(collaboration_id, result)

    def upload(self, collaboration_id: str, locator: Any, paths: Any) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        try:
            files = self.policy.validate_uploads(paths)
        except PolicyError as exc:
            raise CollaborationError(str(exc)) from exc
        encoded = json.dumps([str(path) for path in files], separators=(",", ":"))
        hashes = [_file_sha256(path) for path in files]
        result = self.client.run(
            _program(
                collaboration,
                "upload",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "before_mutation"},
                    {
                        "op": "set_private_files",
                        "locator": semantic_locator,
                        "slot": "upload.files",
                        "max_files": len(files),
                    },
                    {"op": "detach_debugger"},
                ],
                capability="mutation",
                private_slots=["upload.files"],
                intent={"locator": semantic_locator, "file_sha256": hashes},
            ),
            private_values={"upload.files": encoded},
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        self._record("upload", {"locator": semantic_locator, "file_sha256": hashes})
        return self._mutation_receipt(collaboration_id, result)

    def download(
        self,
        collaboration_id: str,
        locator: Any,
        *,
        timeout_ms: int = 30_000,
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        if not self.policy.download_roots:
            raise CollaborationError(
                "no download roots are registered in the local browser policy"
            )
        result = self.client.run(
            _program(
                collaboration,
                "download",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {
                        "op": "start_download_capture",
                        "private_result": "downloads",
                        "max_items": 4,
                    },
                    {"op": "before_mutation"},
                    {"op": "click_ax", "locator": semantic_locator},
                    {"op": "stop_download_capture", "timeout_ms": timeout_ms},
                    {"op": "detach_debugger"},
                ],
                capability="mutation",
                private_fields=["downloads"],
                timeout_ms=max(1000, timeout_ms),
                max_repeat=20,
                intent={"locator": semantic_locator, "timeout_ms": timeout_ms},
            ),
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        verified = []
        for item in result["private"]["downloads"]["items"]:
            if item.get("state") != "complete" or item.get("danger") not in {
                "safe",
                "accepted",
            }:
                raise CollaborationError(
                    "a downloaded file was incomplete or marked unsafe"
                )
            try:
                path = self.policy.validate_download(item.get("filename"))
            except PolicyError as exc:
                raise CollaborationError(str(exc)) from exc
            verified.append(
                {
                    "mime_type": item.get("mime", ""),
                    "size": path.stat().st_size,
                    "sha256": _file_sha256(path),
                    "path": str(path),
                    "danger": item.get("danger", "unknown"),
                }
            )
        self._record("download", {"locator": semantic_locator, "count": len(verified)})
        return {
            "status": "ok",
            "collaboration_id": collaboration_id,
            "downloads": verified,
        }

    def diagnostics(
        self, collaboration_id: str, *, duration_ms: int = 1000
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        if type(duration_ms) is not int or not 20 <= duration_ms <= 30_000:
            raise CollaborationError("duration_ms must be between 20 and 30000")
        private_fields = [
            "diagnostics.logs",
            "diagnostics.requests",
            "diagnostics.console",
            "diagnostics.performance",
        ]
        actions = [
            {"op": "open_or_focus_exact_url"},
            {"op": "assert_exact_target"},
            {"op": "attach_debugger"},
            {
                "op": "start_log_capture",
                "private_result": private_fields[0],
                "max_entries": 100,
                "max_text_bytes": 4096,
            },
            {
                "op": "start_request_capture",
                "private_result": private_fields[1],
                "max_entries": 100,
                "max_url_bytes": 4096,
            },
            {
                "op": "start_console_capture",
                "private_result": private_fields[2],
                "max_entries": 100,
                "max_arguments": 10,
                "max_argument_bytes": 4096,
            },
            {"op": "wait_duration", "duration_ms": duration_ms},
            {
                "op": "capture_performance_private",
                "private_result": private_fields[3],
                "max_metrics": 100,
            },
            {"op": "stop_console_capture"},
            {"op": "stop_request_capture"},
            {"op": "stop_log_capture"},
            {"op": "detach_debugger"},
        ]
        result = self.client.run(
            _program(
                collaboration,
                "diagnostics",
                actions,
                private_fields=private_fields,
                timeout_ms=max(1000, duration_ms + 5000),
                intent={"duration_ms": duration_ms},
            )
        )
        self._require_ok(result)
        return {
            "status": "ok",
            "collaboration_id": collaboration_id,
            **result["private"],
        }

    def credential_fill(
        self, collaboration_id: str, locator: Any, *, broker: str
    ) -> dict[str, Any]:
        collaboration = self._collaboration(collaboration_id)
        semantic_locator = _validate_locator(locator)
        if broker not in {"onepassword", "browser-password-manager"}:
            raise CollaborationError("broker is unsupported")
        result = self.client.run(
            _program(
                collaboration,
                "credential-fill",
                [
                    {"op": "open_or_focus_exact_url"},
                    {"op": "assert_exact_target"},
                    {"op": "attach_debugger"},
                    {"op": "focus_ax", "locator": semantic_locator},
                    {"op": "before_mutation"},
                    {"op": "trigger_credential_broker", "broker": broker},
                    {"op": "detach_debugger"},
                ],
                capability="mutation",
                intent={"locator": semantic_locator, "broker": broker},
            ),
            before_mutation=self.authorize_mutation,
        )
        self._require_ok(result)
        self._record("credential-fill", {"locator": semantic_locator, "broker": broker})
        return self._mutation_receipt(collaboration_id, result)

    def recording_start(self) -> dict[str, Any]:
        if self._recording is not None:
            raise CollaborationError("a workflow recording is already active")
        recording_id = os.urandom(16).hex()
        self._recording = {
            "recording_id": recording_id,
            "started_at": time.time(),
            "steps": [],
        }
        return {"status": "recording", "recording_id": recording_id}

    def recording_status(self) -> dict[str, Any]:
        value = self._recording
        return {
            "recording": value is not None,
            "step_count": len(value["steps"]) if value else 0,
        }

    def recording_stop(self) -> dict[str, Any]:
        if self._recording is None:
            raise CollaborationError("no workflow recording is active")
        draft = self._recording
        self._recording = None
        macro = {
            "protocol": "llm-wiki-browser-workflow-draft/v1",
            "recording_id": draft["recording_id"],
            "steps": draft["steps"],
            "review_required": True,
            "replayable": False,
        }
        macro["sha256"] = _canonical_hash(macro)
        return macro

    def _record(self, operation: str, arguments: dict[str, Any]) -> None:
        if self._recording is None:
            return
        if len(self._recording["steps"]) >= 200:
            raise CollaborationError(
                "workflow recording reached its bounded step limit"
            )
        self._recording["steps"].append(
            {"operation": operation, "arguments": arguments}
        )

    def schedule_snapshot(
        self,
        collaboration_id: str,
        *,
        delay_seconds: int,
        max_items: int = 400,
    ) -> dict[str, Any]:
        self._collaboration(collaboration_id)
        if type(delay_seconds) is not int or not 1 <= delay_seconds <= 86_400:
            raise CollaborationError("delay_seconds must be between 1 and 86400")
        if type(max_items) is not int or not 1 <= max_items <= 1500:
            raise CollaborationError("max_items must be between 1 and 1500")
        schedule_id = os.urandom(16).hex()

        def execute() -> None:
            with self._schedule_lock:
                job = self._schedules.get(schedule_id)
                if not job or job["state"] != "scheduled":
                    return
                job["state"] = "running"
            try:
                result = self.snapshot(collaboration_id, max_items=max_items)
                with self._schedule_lock:
                    job = self._schedules.get(schedule_id)
                    if job:
                        job["state"] = "complete"
                        job["result"] = result
            except BaseException:
                with self._schedule_lock:
                    job = self._schedules.get(schedule_id)
                    if job:
                        job["state"] = "failed"

        timer = threading.Timer(delay_seconds, execute)
        timer.daemon = True
        with self._schedule_lock:
            active = sum(
                1
                for job in self._schedules.values()
                if job["state"] in {"scheduled", "running"}
            )
            if active >= MAX_ACTIVE_SCHEDULES:
                raise CollaborationError("too many active scheduled snapshots")
            while len(self._schedules) >= MAX_RETAINED_SCHEDULES:
                terminal = next(
                    (
                        key
                        for key, job in self._schedules.items()
                        if job["state"] in {"cancelled", "failed"}
                    ),
                    None,
                )
                if terminal is None:
                    raise CollaborationError(
                        "too many completed scheduled snapshots await retrieval"
                    )
                del self._schedules[terminal]
            self._schedules[schedule_id] = {
                "state": "scheduled",
                "timer": timer,
                "result": None,
            }
        timer.start()
        return {"status": "scheduled", "schedule_id": schedule_id}

    def schedule_status(self) -> dict[str, Any]:
        with self._schedule_lock:
            schedules = [
                {"schedule_id": schedule_id, "state": job["state"]}
                for schedule_id, job in self._schedules.items()
            ]
        return {"schedules": schedules}

    def schedule_cancel(self, schedule_id: Any) -> dict[str, Any]:
        if not isinstance(schedule_id, str) or not re.fullmatch(
            r"[a-f0-9]{32}", schedule_id
        ):
            raise CollaborationError("schedule_id is invalid")
        with self._schedule_lock:
            job = self._schedules.get(schedule_id)
            if not job or job["state"] != "scheduled":
                raise CollaborationError("the schedule is not cancellable")
            job["timer"].cancel()
            job["state"] = "cancelled"
        return {"status": "cancelled", "schedule_id": schedule_id}

    def schedule_result(self, schedule_id: Any) -> dict[str, Any]:
        if not isinstance(schedule_id, str) or not re.fullmatch(
            r"[a-f0-9]{32}", schedule_id
        ):
            raise CollaborationError("schedule_id is invalid")
        with self._schedule_lock:
            job = self._schedules.get(schedule_id)
            if not job:
                raise CollaborationError("the schedule is unavailable")
            state = job["state"]
            if state != "complete":
                return {"schedule_id": schedule_id, "state": state}
            result = job["result"]
            del self._schedules[schedule_id]
        return {"schedule_id": schedule_id, "state": "complete", "result": result}

    @staticmethod
    def _require_ok(result: dict[str, Any]) -> None:
        if result.get("status") != "ok":
            code = result.get("error", "browser-operation-failed")
            raise CollaborationError(f"browser executor failed: {code}")

    @staticmethod
    def _mutation_receipt(
        collaboration_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
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
