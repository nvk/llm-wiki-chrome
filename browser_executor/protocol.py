from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Iterator
from urllib.parse import urlsplit

BROWSER_PROTOCOL = "llm-wiki-browser-executor/v1"
IDENTIFIER = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
PROGRAM_IDENTIFIER = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?$")
PRIVATE_FIELD = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,126}[a-z0-9])?$")

MAX_PROGRAM_BYTES = 262_144
MAX_STRING_BYTES = 16_384
TOP_LEVEL_KEYS = {
    "protocol",
    "program_id",
    "program_sha256",
    "plan_sha256",
    "driver",
    "capability",
    "target",
    "limits",
    "private_slots",
    "actions",
    "result",
}

ALLOWED_OPERATIONS = {
    "open_or_focus_exact_url",
    "navigate_same_origin",
    "create_same_origin_tab",
    "navigate_history",
    "close_target_tab",
    "reload_exact_target",
    "assert_exact_target",
    "attach_debugger",
    "detach_debugger",
    "wait_ax",
    "wait_dom",
    "assert_ax",
    "first_success",
    "click_ax",
    "click_dom",
    "focus_ax",
    "hover_ax",
    "drag_ax",
    "select_ax_option",
    "scroll_ax_into_view",
    "dispatch_key_chord",
    "insert_private_text",
    "assert_ax_private_value",
    "assert_ax_private_sha256",
    "extract_ax",
    "extract_ax_collection",
    "collect_ax_by_scrolling",
    "capture_viewport_private",
    "capture_region_private",
    "capture_full_page_private",
    "extract_ax_geometry",
    "capture_performance_private",
    "scroll_viewport",
    "wait_duration",
    "set_private_files",
    "start_download_capture",
    "stop_download_capture",
    "handle_dialog",
    "trigger_credential_broker",
    "start_log_capture",
    "stop_log_capture",
    "start_request_capture",
    "stop_request_capture",
    "start_console_capture",
    "stop_console_capture",
    "before_mutation",
}
FORBIDDEN_KEYS = {
    "javascript",
    "script",
    "expression",
    "runtime_evaluate",
    "cdp_method",
    "cookie",
    "storage",
    "network",
}
MUTATION_ONLY = {
    "insert_private_text",
    "before_mutation",
    "drag_ax",
    "select_ax_option",
    "set_private_files",
    "handle_dialog",
    "trigger_credential_broker",
    "create_same_origin_tab",
    "navigate_history",
    "close_target_tab",
}
PUBLIC_RESULT_FIELDS = {
    "status",
    "action_count",
    "mutation_started",
    "private_result_count",
}
LOCATOR_KEYS = {
    "selector",
    "role",
    "roles",
    "name",
    "name_contains",
    "name_contains_any",
    "name_matches",
    "within",
    "within_name_contains_any",
    "ordinal",
    "visible",
    "checked",
    "focused",
    "unique",
}
ACTION_KEYS = {
    "open_or_focus_exact_url": {"op"},
    "navigate_same_origin": {"op", "url"},
    "create_same_origin_tab": {"op", "url"},
    "navigate_history": {"op", "direction", "expected_url"},
    "close_target_tab": {"op"},
    "reload_exact_target": {"op", "ignore_cache"},
    "assert_exact_target": {"op"},
    "attach_debugger": {"op"},
    "detach_debugger": {"op"},
    "before_mutation": {"op"},
    "stop_log_capture": {"op"},
    "stop_request_capture": {"op"},
    "stop_console_capture": {"op"},
    "wait_ax": {"op", "locator", "timeout_ms"},
    "wait_dom": {"op", "locator", "timeout_ms"},
    "assert_ax": {"op", "locator"},
    "click_ax": {"op", "locator"},
    "click_dom": {"op", "locator"},
    "focus_ax": {"op", "locator"},
    "hover_ax": {"op", "locator"},
    "scroll_ax_into_view": {"op", "locator"},
    "drag_ax": {"op", "locator", "destination", "steps"},
    "select_ax_option": {"op", "locator", "option_locator"},
    "dispatch_key_chord": {"op", "keys"},
    "insert_private_text": {"op", "slot", "replace_all"},
    "assert_ax_private_value": {"op", "slot"},
    "assert_ax_private_sha256": {"op", "slot", "locator", "fields", "max_items"},
    "extract_ax": {"op", "locator", "fields", "private_result", "max_items"},
    "extract_ax_collection": {"op", "locator", "fields", "private_result", "max_items"},
    "collect_ax_by_scrolling": {
        "op",
        "locator",
        "fields",
        "private_result",
        "max_items",
        "direction",
        "distance_px",
        "max_scrolls",
        "settle_ms",
        "dedupe_fields",
        "stable_rounds",
        "scroll_anchor",
    },
    "capture_viewport_private": {"op", "private_result", "quality", "max_bytes"},
    "capture_region_private": {
        "op",
        "private_result",
        "quality",
        "max_bytes",
        "x",
        "y",
        "width",
        "height",
    },
    "capture_full_page_private": {
        "op",
        "private_result",
        "quality",
        "max_bytes",
        "max_width",
        "max_height",
    },
    "extract_ax_geometry": {"op", "locator", "private_result", "max_items"},
    "capture_performance_private": {"op", "private_result", "max_metrics"},
    "scroll_viewport": {"op", "direction", "distance_px"},
    "wait_duration": {"op", "duration_ms"},
    "set_private_files": {"op", "locator", "slot", "max_files"},
    "start_download_capture": {"op", "private_result", "max_items"},
    "stop_download_capture": {"op", "timeout_ms"},
    "handle_dialog": {"op", "accept", "prompt_slot"},
    "trigger_credential_broker": {"op", "broker"},
    "start_log_capture": {"op", "private_result", "max_entries", "max_text_bytes"},
    "start_request_capture": {"op", "private_result", "max_entries", "max_url_bytes"},
    "start_console_capture": {
        "op",
        "private_result",
        "max_entries",
        "max_arguments",
        "max_argument_bytes",
    },
    "first_success": {"op", "branches"},
}
LOCATOR_OPERATIONS = {
    "wait_ax",
    "wait_dom",
    "assert_ax",
    "click_ax",
    "click_dom",
    "focus_ax",
    "hover_ax",
    "scroll_ax_into_view",
    "drag_ax",
    "select_ax_option",
    "set_private_files",
    "extract_ax_geometry",
    "extract_ax",
    "extract_ax_collection",
    "collect_ax_by_scrolling",
    "assert_ax_private_sha256",
}
DOM_LOCATOR_OPERATIONS = {"wait_dom", "click_dom"}
AX_IDENTITY_KEYS = {
    "role",
    "roles",
    "name",
    "name_contains",
    "name_contains_any",
    "name_matches",
    "within",
    "within_name_contains_any",
}
EXTRACTION_FIELDS = {
    "name",
    "role",
    "value",
    "description",
    "url",
    "checked",
    "focused",
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


class ProtocolError(ValueError):
    """Raised when a browser execution program exceeds its bounded contract."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def canonical_program_sha256(program: dict[str, Any]) -> str:
    value = copy.deepcopy(program)
    value.pop("program_sha256", None)
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _reject_unknown_keys(value: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = set(value).difference(allowed)
    if unknown:
        raise ProtocolError(f"{path} contains unsupported fields")


def _bounded_string(
    value: Any, path: str, *, pattern: re.Pattern[str] | None = None
) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{path} must be a non-empty string")
    if len(value.encode("utf-8")) > MAX_STRING_BYTES:
        raise ProtocolError(f"{path} is too large")
    if pattern is not None and not pattern.fullmatch(value):
        raise ProtocolError(f"{path} has an invalid identifier")
    return value


def _check_forbidden_keys(value: Any, path: str = "program") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).lower()
            if lowered in FORBIDDEN_KEYS:
                raise ProtocolError(f"{path} contains forbidden key {key!r}")
            _check_forbidden_keys(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_forbidden_keys(child, f"{path}[{index}]")


def _path_matches_prefix(path: str, prefix: str) -> bool:
    return (
        path == prefix
        or (prefix.endswith("/") and path.startswith(prefix))
        or path.startswith(prefix + "/")
    )


def iter_actions(
    actions: list[dict[str, Any]], depth: int = 0
) -> Iterator[dict[str, Any]]:
    if depth > 4:
        raise ProtocolError("action nesting exceeds four levels")
    for action in actions:
        if not isinstance(action, dict):
            raise ProtocolError("every action must be an object")
        yield action
        branches = action.get("branches")
        if action.get("op") == "first_success":
            if not isinstance(branches, list) or not 1 <= len(branches) <= 4:
                raise ProtocolError("first_success requires one to four branches")
            for branch in branches:
                if not isinstance(branch, list) or not branch:
                    raise ProtocolError(
                        "first_success branches must be non-empty arrays"
                    )
                yield from iter_actions(branch, depth + 1)
        elif branches is not None:
            raise ProtocolError("only first_success may contain branches")


def _validate_target(target: Any) -> None:
    if not isinstance(target, dict):
        raise ProtocolError("target must be an object")
    _reject_unknown_keys(
        target,
        {"url", "origin", "path_prefixes", "collaboration_id"},
        "target",
    )
    raw_url = target.get("url")
    raw_origin = target.get("origin")
    if not isinstance(raw_url, str) or not isinstance(raw_origin, str):
        raise ProtocolError("target url and origin must be strings")
    url = urlsplit(raw_url)
    origin = urlsplit(raw_origin)
    if (
        url.scheme != "https"
        or origin.scheme != "https"
        or not url.hostname
        or url.username is not None
        or url.password is not None
    ):
        raise ProtocolError("target must use an exact HTTPS URL and origin")
    expected_origin = f"{url.scheme}://{url.netloc}"
    if raw_origin != expected_origin or origin.path or origin.query or origin.fragment:
        raise ProtocolError("target origin does not exactly match the target URL")
    collaboration_id = target.get("collaboration_id")
    if not isinstance(collaboration_id, str) or not SHA256.fullmatch(collaboration_id):
        raise ProtocolError("target requires an exact active collaboration id")
    prefixes = target.get("path_prefixes")
    if not isinstance(prefixes, list) or not prefixes:
        raise ProtocolError("target requires at least one path prefix")
    if len(prefixes) > 8:
        raise ProtocolError("target path prefixes must be unique and bounded")
    if not all(
        isinstance(item, str)
        and item.startswith("/")
        and "?" not in item
        and "#" not in item
        and len(item.encode("utf-8")) <= 2048
        for item in prefixes
    ):
        raise ProtocolError("target path prefixes must be absolute paths")
    if len(prefixes) != len(set(prefixes)):
        raise ProtocolError("target path prefixes must be unique and bounded")
    if not any(_path_matches_prefix(url.path, item) for item in prefixes):
        raise ProtocolError("target URL is outside its approved path prefixes")


def _validate_navigation_url(raw_url: Any, target: dict[str, Any]) -> None:
    if not isinstance(raw_url, str) or len(raw_url.encode("utf-8")) > 16384:
        raise ProtocolError("navigation URL must be a bounded string")
    value = urlsplit(raw_url)
    if (
        value.scheme != "https"
        or value.username is not None
        or value.password is not None
        or value.fragment
        or f"{value.scheme}://{value.netloc}" != target["origin"]
        or not any(
            _path_matches_prefix(value.path, prefix)
            for prefix in target["path_prefixes"]
        )
    ):
        raise ProtocolError("navigation URL is outside the exact target policy")


def _validate_limits(limits: Any) -> dict[str, int]:
    if not isinstance(limits, dict):
        raise ProtocolError("limits must be an object")
    _reject_unknown_keys(limits, {"timeout_ms", "max_actions", "max_repeat"}, "limits")
    timeout = limits.get("timeout_ms")
    maximum = limits.get("max_actions")
    repeat = limits.get("max_repeat")
    if type(timeout) is not int or not 1000 <= timeout <= 300000:
        raise ProtocolError("timeout_ms must be between 1000 and 300000")
    if type(maximum) is not int or not 1 <= maximum <= 200:
        raise ProtocolError("max_actions must be between 1 and 200")
    if type(repeat) is not int or not 1 <= repeat <= 20:
        raise ProtocolError("max_repeat must be between 1 and 20")
    return {"timeout_ms": timeout, "max_actions": maximum, "max_repeat": repeat}


def _validate_locator(locator: Any, path: str, depth: int = 0) -> None:
    if depth > 2 or not isinstance(locator, dict) or not locator:
        raise ProtocolError(f"{path} must be a bounded locator object")
    _reject_unknown_keys(locator, LOCATOR_KEYS, path)
    if "selector" in locator:
        _bounded_string(locator["selector"], f"{path}.selector")
    if "role" in locator:
        _bounded_string(locator["role"], f"{path}.role", pattern=IDENTIFIER)
    if "roles" in locator:
        roles = locator["roles"]
        if (
            not isinstance(roles, list)
            or not 1 <= len(roles) <= 8
            or not all(
                isinstance(item, str) and IDENTIFIER.fullmatch(item) for item in roles
            )
        ):
            raise ProtocolError(f"{path}.roles must be unique role identifiers")
        if len(roles) != len(set(roles)):
            raise ProtocolError(f"{path}.roles must be unique role identifiers")
    for key in ("name", "name_contains", "name_matches"):
        if key in locator:
            _bounded_string(locator[key], f"{path}.{key}")
    if "name_matches" in locator:
        pattern = locator["name_matches"]
        if (
            len(pattern.encode("utf-8")) > 256
            or any(token in pattern for token in ("(", ")", "{", "}"))
            or re.search(r"(?:[+*?]){2,}", pattern)
            or re.search(r"\\(?:[1-9]|k[<{])", pattern)
        ):
            raise ProtocolError(f"{path}.name_matches is outside the safe regex subset")
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ProtocolError(f"{path}.name_matches is invalid") from exc
    for key in ("name_contains_any", "within_name_contains_any"):
        if key in locator:
            items = locator[key]
            if (
                not isinstance(items, list)
                or not 1 <= len(items) <= 12
                or not all(
                    isinstance(item, str) and item and len(item.encode("utf-8")) <= 512
                    for item in items
                )
            ):
                raise ProtocolError(f"{path}.{key} must be a bounded string array")
    if "ordinal" in locator and (
        type(locator["ordinal"]) is not int or not 0 <= locator["ordinal"] <= 1000
    ):
        raise ProtocolError(f"{path}.ordinal is out of bounds")
    for key in ("visible", "checked", "focused", "unique"):
        if key in locator and not isinstance(locator[key], bool):
            raise ProtocolError(f"{path}.{key} must be boolean")
    if "within" in locator:
        _validate_locator(locator["within"], f"{path}.within", depth + 1)


def _validate_ax_locator_shape(locator: dict[str, Any]) -> None:
    if "selector" in locator or "visible" in locator:
        raise ProtocolError(
            "AX locators do not accept DOM selector or visibility predicates"
        )
    if not AX_IDENTITY_KEYS.intersection(locator):
        raise ProtocolError("AX locators require a semantic identity predicate")
    if "within" in locator:
        _validate_ax_locator_shape(locator["within"])


def _validate_dom_locator_shape(locator: dict[str, Any]) -> None:
    if set(locator).difference({"selector", "visible"}) or "selector" not in locator:
        raise ProtocolError(
            "DOM locators require only a selector and optional visibility"
        )


def _validate_action(
    action: dict[str, Any],
    slots: set[str],
    private_results: set[str],
    target: dict[str, Any],
    index: int,
) -> None:
    operation = action.get("op")
    if operation not in ALLOWED_OPERATIONS:
        raise ProtocolError("program contains an unsupported operation")
    _reject_unknown_keys(action, ACTION_KEYS[operation], f"action[{index}]")
    if operation in {"navigate_same_origin", "create_same_origin_tab"}:
        _validate_navigation_url(action.get("url"), target)
    if operation == "navigate_history":
        if action.get("direction") not in {"back", "forward"}:
            raise ProtocolError("history direction must be back or forward")
        _validate_navigation_url(action.get("expected_url"), target)
    if operation == "reload_exact_target" and not isinstance(
        action.get("ignore_cache"), bool
    ):
        raise ProtocolError("reload_exact_target requires ignore_cache")
    if operation in LOCATOR_OPERATIONS:
        _validate_locator(action.get("locator"), f"action[{index}].locator")
        if operation in DOM_LOCATOR_OPERATIONS:
            _validate_dom_locator_shape(action["locator"])
        else:
            _validate_ax_locator_shape(action["locator"])
    if operation == "drag_ax":
        _validate_locator(action.get("destination"), f"action[{index}].destination")
        _validate_ax_locator_shape(action["destination"])
        if type(action.get("steps")) is not int or not 2 <= action["steps"] <= 50:
            raise ProtocolError("drag steps are out of bounds")
    if operation == "select_ax_option":
        _validate_locator(
            action.get("option_locator"), f"action[{index}].option_locator"
        )
        _validate_ax_locator_shape(action["option_locator"])
    if operation in {"wait_ax", "wait_dom"}:
        timeout = action.get("timeout_ms")
        if type(timeout) is not int or not 50 <= timeout <= 300000:
            raise ProtocolError("wait timeout_ms must be between 50 and 300000")
    if operation == "dispatch_key_chord":
        keys = action.get("keys")
        if (
            not isinstance(keys, list)
            or not 1 <= len(keys) <= 5
            or not all(isinstance(key, str) and key in KEY_NAMES for key in keys)
        ):
            raise ProtocolError("key chord is invalid or unbounded")
        if len(keys) != len(set(keys)):
            raise ProtocolError("key chord is invalid or unbounded")
    if operation in {
        "insert_private_text",
        "assert_ax_private_value",
        "assert_ax_private_sha256",
        "set_private_files",
    }:
        if action.get("slot") not in slots:
            raise ProtocolError("action references an undeclared private slot")
        if operation == "insert_private_text" and not isinstance(
            action.get("replace_all"), bool
        ):
            raise ProtocolError("insert_private_text requires replace_all")
        if operation == "set_private_files" and (
            type(action.get("max_files")) is not int
            or not 1 <= action["max_files"] <= 16
        ):
            raise ProtocolError("file upload max_files is out of bounds")
    if operation in {
        "extract_ax",
        "extract_ax_collection",
        "collect_ax_by_scrolling",
        "assert_ax_private_sha256",
    }:
        fields = action.get("fields")
        if (
            not isinstance(fields, list)
            or not 1 <= len(fields) <= len(EXTRACTION_FIELDS)
            or not all(isinstance(field, str) for field in fields)
            or not set(fields).issubset(EXTRACTION_FIELDS)
        ):
            raise ProtocolError("extraction fields are invalid")
        if len(fields) != len(set(fields)):
            raise ProtocolError("extraction fields are invalid")
        private_result = action.get("private_result")
        if (
            operation != "assert_ax_private_sha256"
            and private_result not in private_results
        ):
            raise ProtocolError("extraction references an undeclared private result")
        max_items = action.get("max_items")
        maximum = 100 if operation == "extract_ax" else 5000
        if type(max_items) is not int or not 1 <= max_items <= maximum:
            raise ProtocolError("extraction max_items is out of bounds")
    if operation == "collect_ax_by_scrolling":
        _validate_locator(action.get("scroll_anchor"), f"action[{index}].scroll_anchor")
        _validate_ax_locator_shape(action["scroll_anchor"])
    if operation in {
        "capture_viewport_private",
        "capture_region_private",
        "capture_full_page_private",
    }:
        if action.get("private_result") not in private_results:
            raise ProtocolError("screenshot references an undeclared private result")
        if type(action.get("quality")) is not int or not 10 <= action["quality"] <= 90:
            raise ProtocolError("screenshot quality is out of bounds")
        if (
            type(action.get("max_bytes")) is not int
            or not 16384 <= action["max_bytes"] <= 262144
        ):
            raise ProtocolError("screenshot max_bytes is out of bounds")
    if operation == "capture_region_private":
        for key in ("x", "y"):
            if (
                type(action.get(key)) not in {int, float}
                or not 0 <= action[key] <= 100000
            ):
                raise ProtocolError("screenshot region origin is out of bounds")
        for key in ("width", "height"):
            if (
                type(action.get(key)) not in {int, float}
                or not 1 <= action[key] <= 10000
            ):
                raise ProtocolError("screenshot region size is out of bounds")
    if operation == "capture_full_page_private":
        for key in ("max_width", "max_height"):
            if type(action.get(key)) is not int or not 1 <= action[key] <= 20000:
                raise ProtocolError("full-page screenshot dimensions are out of bounds")
    if operation == "extract_ax_geometry":
        if action.get("private_result") not in private_results:
            raise ProtocolError(
                "geometry extraction references an undeclared private result"
            )
        if (
            type(action.get("max_items")) is not int
            or not 1 <= action["max_items"] <= 500
        ):
            raise ProtocolError("geometry extraction max_items is out of bounds")
    if operation == "capture_performance_private":
        if action.get("private_result") not in private_results:
            raise ProtocolError(
                "performance capture references an undeclared private result"
            )
        if (
            type(action.get("max_metrics")) is not int
            or not 1 <= action["max_metrics"] <= 100
        ):
            raise ProtocolError("performance max_metrics is out of bounds")
    if operation in {"scroll_viewport", "collect_ax_by_scrolling"}:
        if action.get("direction") not in {"up", "down"}:
            raise ProtocolError("scroll direction must be up or down")
        if (
            type(action.get("distance_px")) is not int
            or not 1 <= action["distance_px"] <= 10000
        ):
            raise ProtocolError("scroll distance_px is out of bounds")
    if operation == "collect_ax_by_scrolling":
        max_scrolls = action.get("max_scrolls")
        settle_ms = action.get("settle_ms")
        stable_rounds = action.get("stable_rounds")
        dedupe_fields = action.get("dedupe_fields")
        fields = action["fields"]
        if type(max_scrolls) is not int or not 1 <= max_scrolls <= 20:
            raise ProtocolError("scrolling collection max_scrolls is out of bounds")
        if type(settle_ms) is not int or not 50 <= settle_ms <= 3000:
            raise ProtocolError("scrolling collection settle_ms is out of bounds")
        if (
            type(stable_rounds) is not int
            or not 1 <= stable_rounds <= 3
            or stable_rounds > max_scrolls
        ):
            raise ProtocolError("scrolling collection stable_rounds is out of bounds")
        if (
            not isinstance(dedupe_fields, list)
            or not 1 <= len(dedupe_fields) <= len(fields)
            or len(dedupe_fields) != len(set(dedupe_fields))
            or not set(dedupe_fields).issubset(fields)
        ):
            raise ProtocolError("scrolling collection dedupe_fields are invalid")
    if operation == "wait_duration" and (
        type(action.get("duration_ms")) is not int
        or not 20 <= action["duration_ms"] <= 30000
    ):
        raise ProtocolError("wait duration is out of bounds")
    if operation == "start_download_capture":
        if action.get("private_result") not in private_results:
            raise ProtocolError(
                "download capture references an undeclared private result"
            )
        if (
            type(action.get("max_items")) is not int
            or not 1 <= action["max_items"] <= 16
        ):
            raise ProtocolError("download capture max_items is out of bounds")
    if operation == "stop_download_capture":
        if (
            type(action.get("timeout_ms")) is not int
            or not 100 <= action["timeout_ms"] <= 120000
        ):
            raise ProtocolError("download capture timeout is out of bounds")
    if operation == "handle_dialog":
        if not isinstance(action.get("accept"), bool):
            raise ProtocolError("dialog action requires accept")
        slot = action.get("prompt_slot")
        if slot is not None and slot not in slots:
            raise ProtocolError("dialog action references an undeclared private slot")
        if not action["accept"] and slot is not None:
            raise ProtocolError("dismissed dialogs cannot include prompt text")
    if operation == "trigger_credential_broker" and action.get("broker") not in {
        "onepassword",
        "browser-password-manager",
    }:
        raise ProtocolError("credential broker is unsupported")
    if operation == "start_log_capture":
        if action.get("private_result") not in private_results:
            raise ProtocolError("log capture references an undeclared private result")
        if (
            type(action.get("max_entries")) is not int
            or not 1 <= action["max_entries"] <= 500
        ):
            raise ProtocolError("log capture max_entries is out of bounds")
        if (
            type(action.get("max_text_bytes")) is not int
            or not 256 <= action["max_text_bytes"] <= 16384
        ):
            raise ProtocolError("log capture max_text_bytes is out of bounds")
    if operation == "start_request_capture":
        if action.get("private_result") not in private_results:
            raise ProtocolError(
                "request capture references an undeclared private result"
            )
        if (
            type(action.get("max_entries")) is not int
            or not 1 <= action["max_entries"] <= 500
        ):
            raise ProtocolError("request capture max_entries is out of bounds")
        if (
            type(action.get("max_url_bytes")) is not int
            or not 256 <= action["max_url_bytes"] <= 16384
        ):
            raise ProtocolError("request capture max_url_bytes is out of bounds")
    if operation == "start_console_capture":
        if action.get("private_result") not in private_results:
            raise ProtocolError(
                "console capture references an undeclared private result"
            )
        if (
            type(action.get("max_entries")) is not int
            or not 1 <= action["max_entries"] <= 500
        ):
            raise ProtocolError("console capture max_entries is out of bounds")
        if (
            type(action.get("max_arguments")) is not int
            or not 1 <= action["max_arguments"] <= 20
        ):
            raise ProtocolError("console capture max_arguments is out of bounds")
        if (
            type(action.get("max_argument_bytes")) is not int
            or not 256 <= action["max_argument_bytes"] <= 16384
        ):
            raise ProtocolError("console capture max_argument_bytes is out of bounds")


def validate_program(program: Any) -> dict[str, Any]:
    if not isinstance(program, dict):
        raise ProtocolError("program must be an object")
    if len(canonical_json(program)) > MAX_PROGRAM_BYTES:
        raise ProtocolError("program is too large")
    _reject_unknown_keys(program, TOP_LEVEL_KEYS, "program")
    _check_forbidden_keys(program)
    if program.get("protocol") != BROWSER_PROTOCOL:
        raise ProtocolError("unsupported browser executor protocol")
    _bounded_string(program.get("program_id"), "program_id", pattern=PROGRAM_IDENTIFIER)
    if not SHA256.fullmatch(str(program.get("plan_sha256", ""))):
        raise ProtocolError("plan_sha256 must be lowercase hexadecimal SHA-256")
    if not SHA256.fullmatch(str(program.get("program_sha256", ""))):
        raise ProtocolError("program_sha256 must be lowercase hexadecimal SHA-256")
    driver = program.get("driver")
    if not isinstance(driver, dict):
        raise ProtocolError("driver must be an object")
    _reject_unknown_keys(driver, {"id", "version"}, "driver")
    if not IDENTIFIER.fullmatch(str(driver.get("id", ""))):
        raise ProtocolError("driver requires a stable lowercase ID")
    _bounded_string(driver.get("version"), "driver.version", pattern=PROGRAM_IDENTIFIER)
    capability = program.get("capability")
    if capability not in {"read", "mutation"}:
        raise ProtocolError("capability must be read or mutation")
    _validate_target(program.get("target"))
    limits = _validate_limits(program.get("limits"))
    slots = program.get("private_slots", [])
    if not isinstance(slots, list):
        raise ProtocolError("private_slots must be a unique array")
    if len(slots) > 32 or not all(
        isinstance(slot, str) and PRIVATE_FIELD.fullmatch(slot) for slot in slots
    ):
        raise ProtocolError("private slot names must be non-empty strings")
    if len(slots) != len(set(slots)):
        raise ProtocolError("private_slots must be a unique array")
    raw_actions = program.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise ProtocolError("actions must be a non-empty array")
    flat = list(iter_actions(raw_actions))
    if len(flat) > limits["max_actions"]:
        raise ProtocolError("program exceeds max_actions")
    result = program.get("result")
    if not isinstance(result, dict):
        raise ProtocolError("result must be an object")
    _reject_unknown_keys(result, {"public_fields", "private_fields"}, "result")
    public = result.get("public_fields", [])
    private = result.get("private_fields", [])
    if (
        not isinstance(public, list)
        or not all(isinstance(item, str) for item in public)
        or not set(public).issubset(PUBLIC_RESULT_FIELDS)
    ):
        raise ProtocolError("result requests an unsafe public field")
    if len(public) != len(set(public)):
        raise ProtocolError("result requests an unsafe public field")
    if (
        not isinstance(private, list)
        or len(private) > 32
        or not all(
            isinstance(item, str) and PRIVATE_FIELD.fullmatch(item) for item in private
        )
    ):
        raise ProtocolError("private result fields must be named strings")
    if len(private) != len(set(private)):
        raise ProtocolError("private result fields must be named strings")
    slot_set = set(slots)
    private_result_set = set(private)
    for index, action in enumerate(flat):
        _validate_action(action, slot_set, private_result_set, program["target"], index)
        if (
            action["op"] == "collect_ax_by_scrolling"
            and action["max_scrolls"] > limits["max_repeat"]
        ):
            raise ProtocolError("scrolling collection exceeds max_repeat")
    operations = [action["op"] for action in flat]
    top_level_operations = [action.get("op") for action in raw_actions]
    if (
        top_level_operations[0] != "open_or_focus_exact_url"
        or top_level_operations[-1] not in {"detach_debugger", "close_target_tab"}
        or top_level_operations.count("open_or_focus_exact_url") != 1
        or top_level_operations.count("attach_debugger") != 1
        or top_level_operations.count("detach_debugger") != 1
        or operations.count("open_or_focus_exact_url") != 1
        or operations.count("attach_debugger") != 1
        or operations.count("detach_debugger") != 1
        or operations.index("attach_debugger") >= operations.index("detach_debugger")
        or (
            top_level_operations[-1] == "close_target_tab"
            and top_level_operations[-2] != "detach_debugger"
        )
    ):
        raise ProtocolError(
            "program lifecycle must open once, attach once, and detach last"
        )
    boundary_count = operations.count("before_mutation")
    if capability == "read" and (
        boundary_count or MUTATION_ONLY.intersection(operations)
    ):
        raise ProtocolError("read programs cannot contain mutation actions")
    if capability == "mutation" and (
        boundary_count != 1 or top_level_operations.count("before_mutation") != 1
    ):
        raise ProtocolError("mutation programs require exactly one mutation boundary")
    if capability == "mutation":
        boundary_index = top_level_operations.index("before_mutation")
        if "first_success" in top_level_operations[boundary_index + 1 :]:
            raise ProtocolError(
                "mutation recovery branches must precede the mutation boundary"
            )
    log_starts = operations.count("start_log_capture")
    log_stops = operations.count("stop_log_capture")
    if (
        log_starts != log_stops
        or log_starts > 1
        or top_level_operations.count("start_log_capture") != log_starts
        or top_level_operations.count("stop_log_capture") != log_stops
        or (
            log_starts == 1
            and operations.index("start_log_capture")
            >= operations.index("stop_log_capture")
        )
    ):
        raise ProtocolError("private log capture lifecycle is invalid")
    request_starts = operations.count("start_request_capture")
    request_stops = operations.count("stop_request_capture")
    if (
        request_starts != request_stops
        or request_starts > 1
        or top_level_operations.count("start_request_capture") != request_starts
        or top_level_operations.count("stop_request_capture") != request_stops
        or (
            request_starts == 1
            and operations.index("start_request_capture")
            >= operations.index("stop_request_capture")
        )
    ):
        raise ProtocolError("private request capture lifecycle is invalid")
    console_starts = operations.count("start_console_capture")
    console_stops = operations.count("stop_console_capture")
    if (
        console_starts != console_stops
        or console_starts > 1
        or top_level_operations.count("start_console_capture") != console_starts
        or top_level_operations.count("stop_console_capture") != console_stops
        or (
            console_starts == 1
            and operations.index("start_console_capture")
            >= operations.index("stop_console_capture")
        )
    ):
        raise ProtocolError("private console capture lifecycle is invalid")
    download_starts = operations.count("start_download_capture")
    download_stops = operations.count("stop_download_capture")
    if (
        download_starts != download_stops
        or download_starts > 1
        or top_level_operations.count("start_download_capture") != download_starts
        or top_level_operations.count("stop_download_capture") != download_stops
        or (
            download_starts == 1
            and operations.index("start_download_capture")
            >= operations.index("stop_download_capture")
        )
    ):
        raise ProtocolError("private download capture lifecycle is invalid")
    extracted = {
        action["private_result"]
        for action in flat
        if action["op"]
        in {
            "extract_ax",
            "extract_ax_collection",
            "collect_ax_by_scrolling",
            "capture_viewport_private",
            "start_log_capture",
            "start_request_capture",
            "start_console_capture",
            "capture_region_private",
            "capture_full_page_private",
            "extract_ax_geometry",
            "capture_performance_private",
            "start_download_capture",
        }
    }
    if extracted != private_result_set:
        raise ProtocolError(
            "private result declarations must exactly match extraction actions"
        )
    expected = program["program_sha256"]
    if expected != canonical_program_sha256(program):
        raise ProtocolError("program_sha256 does not match the canonical program")
    return copy.deepcopy(program)
