from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO

from .collaboration import BrowserCollaborationController, collaboration_error_message

MCP_PROTOCOL = "2025-06-18"
SUPPORTED_MCP_PROTOCOLS = {MCP_PROTOCOL, "2025-11-25"}
SERVER_NAME = "llm-wiki-browser-collaboration"
SERVER_VERSION = "0.1.0"


def _object_schema(
    properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


LOCATOR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "description": "A semantic accessibility-tree locator; arbitrary CSS and executable scripts are not accepted.",
    "properties": {
        "role": {"type": "string"},
        "roles": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 8,
        },
        "name": {"type": "string"},
        "name_contains": {"type": "string"},
        "name_contains_any": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 12,
        },
        "name_matches": {"type": "string"},
        "within": {"type": "object"},
        "within_name_contains_any": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 12,
        },
        "ordinal": {"type": "integer", "minimum": 0, "maximum": 1000},
        "checked": {"type": "boolean"},
        "focused": {"type": "boolean"},
        "unique": {"type": "boolean"},
    },
    "additionalProperties": False,
    "minProperties": 1,
}


TOOLS = [
    {
        "name": "browser_status",
        "description": "Check whether the local connector is online and how many tabs are explicitly shared.",
        "inputSchema": _object_schema({}),
    },
    {
        "name": "browser_tabs",
        "description": (
            "List only HTTPS tabs the user explicitly shared by clicking the LLM Wiki Browser "
            "Executor extension. Call this first; never infer or fabricate a collaboration ID."
        ),
        "inputSchema": _object_schema({}),
    },
    {
        "name": "browser_focus",
        "description": "Focus one explicitly shared tab without reading or mutating its page.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            },
            ["collaboration_id"],
        ),
    },
    {
        "name": "browser_open",
        "description": "Open and explicitly grant a new tab on the same origin as an existing shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "url": {"type": "string", "format": "uri", "pattern": "^https://"},
            },
            ["collaboration_id", "url"],
        ),
    },
    {
        "name": "browser_history",
        "description": "Go back or forward only when the caller supplies the exact expected same-origin URL.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "direction": {"type": "string", "enum": ["back", "forward"]},
                "expected_url": {
                    "type": "string",
                    "format": "uri",
                    "pattern": "^https://",
                },
            },
            ["collaboration_id", "direction", "expected_url"],
        ),
    },
    {
        "name": "browser_close",
        "description": "Close one exact explicitly shared tab through a governed mutation boundary.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            },
            ["collaboration_id"],
        ),
    },
    {
        "name": "browser_snapshot",
        "description": "Read a bounded accessibility-tree projection from one explicitly shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "max_items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1500,
                    "default": 400,
                },
            },
            ["collaboration_id"],
        ),
    },
    {
        "name": "browser_screenshot",
        "description": "Capture the current viewport of one explicitly shared tab as a private JPEG result.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "quality": {
                    "type": "integer",
                    "minimum": 10,
                    "maximum": 90,
                    "default": 65,
                },
            },
            ["collaboration_id"],
        ),
    },
    {
        "name": "browser_region_screenshot",
        "description": "Capture one bounded document region from an explicitly shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "x": {"type": "number", "minimum": 0, "maximum": 100000},
                "y": {"type": "number", "minimum": 0, "maximum": 100000},
                "width": {"type": "number", "minimum": 1, "maximum": 10000},
                "height": {"type": "number", "minimum": 1, "maximum": 10000},
                "quality": {
                    "type": "integer",
                    "minimum": 10,
                    "maximum": 90,
                    "default": 65,
                },
            },
            ["collaboration_id", "x", "y", "width", "height"],
        ),
    },
    {
        "name": "browser_full_page_screenshot",
        "description": "Capture a dimension- and byte-capped full-page JPEG from an explicitly shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "quality": {
                    "type": "integer",
                    "minimum": 10,
                    "maximum": 90,
                    "default": 60,
                },
            },
            ["collaboration_id"],
        ),
    },
    {
        "name": "browser_geometry",
        "description": "Return bounded private geometry for semantic elements in an explicitly shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
                "max_items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "default": 100,
                },
            },
            ["collaboration_id", "locator"],
        ),
    },
    {
        "name": "browser_wait",
        "description": "Wait for one bounded semantic condition in an explicitly shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 50,
                    "maximum": 300000,
                    "default": 10000,
                },
            },
            ["collaboration_id", "locator"],
        ),
    },
    {
        "name": "browser_navigate",
        "description": "Navigate one explicitly shared tab to an exact same-origin HTTPS URL.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "url": {"type": "string", "format": "uri", "pattern": "^https://"},
                "ignore_cache": {"type": "boolean", "default": False},
            },
            ["collaboration_id", "url"],
        ),
    },
    {
        "name": "browser_reload",
        "description": "Reload one explicitly shared exact tab, optionally bypassing cache.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "ignore_cache": {"type": "boolean", "default": False},
            },
            ["collaboration_id"],
        ),
    },
    {
        "name": "browser_click",
        "description": "Click one uniquely identified accessibility-tree control in an explicitly shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
            },
            ["collaboration_id", "locator"],
        ),
    },
    {
        "name": "browser_hover",
        "description": "Hover one uniquely identified semantic element in an explicitly shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
            },
            ["collaboration_id", "locator"],
        ),
    },
    {
        "name": "browser_select",
        "description": "Open a semantic selector and choose one semantic option.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
                "option_locator": LOCATOR_SCHEMA,
            },
            ["collaboration_id", "locator", "option_locator"],
        ),
    },
    {
        "name": "browser_drag",
        "description": "Drag one semantic element to another using bounded pointer steps.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
                "destination": LOCATOR_SCHEMA,
                "steps": {"type": "integer", "minimum": 2, "maximum": 50, "default": 8},
            },
            ["collaboration_id", "locator", "destination"],
        ),
    },
    {
        "name": "browser_type",
        "description": (
            "Focus one semantic control and insert private text in an explicitly shared tab; "
            "this does not submit the form."
        ),
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
                "text": {"type": "string", "minLength": 1, "maxLength": 16384},
                "replace_all": {"type": "boolean", "default": True},
            },
            ["collaboration_id", "locator", "text"],
        ),
    },
    {
        "name": "browser_key",
        "description": (
            "Dispatch one bounded key chord to an explicitly shared tab. "
            "Modifier and Enter/Tab chords can commit or submit a focused form; "
            "this crosses the governed mutation boundary."
        ),
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                },
            },
            ["collaboration_id", "keys"],
        ),
    },
    {
        "name": "browser_scroll",
        "description": "Scroll the viewport of one explicitly shared tab by a bounded distance.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "direction": {"type": "string", "enum": ["up", "down"]},
                "distance_px": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10000,
                    "default": 700,
                },
            },
            ["collaboration_id", "direction"],
        ),
    },
    {
        "name": "browser_scroll_to",
        "description": "Scroll one semantic element into view in an explicitly shared tab.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
            },
            ["collaboration_id", "locator"],
        ),
    },
    {
        "name": "browser_dialog",
        "description": "Accept or dismiss a browser modal dialog; prompt text stays in a private slot.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "accept": {"type": "boolean"},
                "prompt_text": {"type": "string", "maxLength": 16384},
            },
            ["collaboration_id", "accept"],
        ),
    },
    {
        "name": "browser_upload",
        "description": "Set one file input from paths inside machine-local registered upload roots.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 16,
                },
            },
            ["collaboration_id", "locator", "paths"],
        ),
    },
    {
        "name": "browser_download",
        "description": "Click a semantic download control and verify completed files against registered roots.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
                "timeout_ms": {
                    "type": "integer",
                    "minimum": 100,
                    "maximum": 120000,
                    "default": 30000,
                },
            },
            ["collaboration_id", "locator"],
        ),
    },
    {
        "name": "browser_diagnostics",
        "description": "Capture bounded logs, scalar console events, request metadata, and performance metrics.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "duration_ms": {
                    "type": "integer",
                    "minimum": 20,
                    "maximum": 30000,
                    "default": 1000,
                },
            },
            ["collaboration_id"],
        ),
    },
    {
        "name": "browser_credential_fill",
        "description": "Focus a field and invoke a local password-manager UI without receiving the secret.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "locator": LOCATOR_SCHEMA,
                "broker": {
                    "type": "string",
                    "enum": ["onepassword", "browser-password-manager"],
                },
            },
            ["collaboration_id", "locator", "broker"],
        ),
    },
    {
        "name": "browser_record_start",
        "description": "Start an in-memory typed workflow draft.",
        "inputSchema": _object_schema({}),
    },
    {
        "name": "browser_record_status",
        "description": "Return content-free recording state.",
        "inputSchema": _object_schema({}),
    },
    {
        "name": "browser_record_stop",
        "description": "Stop recording and return a review-required workflow draft.",
        "inputSchema": _object_schema({}),
    },
    {
        "name": "browser_schedule_snapshot",
        "description": "Schedule one in-memory read-only snapshot while the exact grant and MCP process remain live.",
        "inputSchema": _object_schema(
            {
                "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "delay_seconds": {"type": "integer", "minimum": 1, "maximum": 86400},
                "max_items": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 1500,
                    "default": 400,
                },
            },
            ["collaboration_id", "delay_seconds"],
        ),
    },
    {
        "name": "browser_schedule_status",
        "description": "Return content-free state for in-memory read-only schedules.",
        "inputSchema": _object_schema({}),
    },
    {
        "name": "browser_schedule_cancel",
        "description": "Cancel one pending in-memory read-only schedule.",
        "inputSchema": _object_schema(
            {"schedule_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}},
            ["schedule_id"],
        ),
    },
    {
        "name": "browser_schedule_result",
        "description": "Retrieve and remove one completed private read-only scheduled result.",
        "inputSchema": _object_schema(
            {"schedule_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"}},
            ["schedule_id"],
        ),
    },
]


class McpServer:
    def __init__(
        self, controller: BrowserCollaborationController | None = None
    ) -> None:
        self.controller = controller or BrowserCollaborationController()

    def _tool_result(self, name: str, arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        if name == "browser_status":
            self._require_arguments(arguments, set(), set())
            value: Any = self.controller.status()
        elif name == "browser_tabs":
            self._require_arguments(arguments, set(), set())
            value = {"tabs": self.controller.tabs()}
        elif name == "browser_focus":
            self._require_arguments(
                arguments, {"collaboration_id"}, {"collaboration_id"}
            )
            value = self.controller.focus(arguments.get("collaboration_id"))
        elif name == "browser_open":
            self._require_arguments(
                arguments, {"collaboration_id", "url"}, {"collaboration_id", "url"}
            )
            value = self.controller.open(
                arguments.get("collaboration_id"), arguments.get("url")
            )
        elif name == "browser_history":
            self._require_arguments(
                arguments,
                {"collaboration_id", "direction", "expected_url"},
                {"collaboration_id", "direction", "expected_url"},
            )
            value = self.controller.history(
                arguments.get("collaboration_id"),
                direction=arguments.get("direction"),
                expected_url=arguments.get("expected_url"),
            )
        elif name == "browser_close":
            self._require_arguments(
                arguments, {"collaboration_id"}, {"collaboration_id"}
            )
            value = self.controller.close(arguments.get("collaboration_id"))
        elif name == "browser_snapshot":
            self._require_arguments(
                arguments, {"collaboration_id", "max_items"}, {"collaboration_id"}
            )
            value = self.controller.snapshot(
                arguments.get("collaboration_id"),
                max_items=arguments.get("max_items", 400),
            )
        elif name == "browser_screenshot":
            self._require_arguments(
                arguments, {"collaboration_id", "quality"}, {"collaboration_id"}
            )
            value = self.controller.screenshot(
                arguments.get("collaboration_id"),
                quality=arguments.get("quality", 65),
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "ok",
                                "collaboration_id": value["collaboration_id"],
                                "url": value["url"],
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                    {
                        "type": "image",
                        "data": value["data_base64"],
                        "mimeType": value["mime_type"],
                    },
                ],
                "isError": False,
            }
        elif name in {"browser_region_screenshot", "browser_full_page_screenshot"}:
            if name == "browser_region_screenshot":
                self._require_arguments(
                    arguments,
                    {"collaboration_id", "x", "y", "width", "height", "quality"},
                    {"collaboration_id", "x", "y", "width", "height"},
                )
                value = self.controller.region_screenshot(
                    arguments.get("collaboration_id"),
                    x=arguments.get("x"),
                    y=arguments.get("y"),
                    width=arguments.get("width"),
                    height=arguments.get("height"),
                    quality=arguments.get("quality", 65),
                )
            else:
                self._require_arguments(
                    arguments, {"collaboration_id", "quality"}, {"collaboration_id"}
                )
                value = self.controller.full_page_screenshot(
                    arguments.get("collaboration_id"),
                    quality=arguments.get("quality", 60),
                )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "status": "ok",
                                "collaboration_id": value["collaboration_id"],
                                "url": value["url"],
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    },
                    {
                        "type": "image",
                        "data": value["data_base64"],
                        "mimeType": value["mime_type"],
                    },
                ],
                "isError": False,
            }
        elif name == "browser_geometry":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator", "max_items"},
                {"collaboration_id", "locator"},
            )
            value = self.controller.geometry(
                arguments.get("collaboration_id"),
                arguments.get("locator"),
                max_items=arguments.get("max_items", 100),
            )
        elif name == "browser_wait":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator", "timeout_ms"},
                {"collaboration_id", "locator"},
            )
            value = self.controller.wait(
                arguments.get("collaboration_id"),
                arguments.get("locator"),
                timeout_ms=arguments.get("timeout_ms", 10_000),
            )
        elif name == "browser_navigate":
            self._require_arguments(
                arguments,
                {"collaboration_id", "url", "ignore_cache"},
                {"collaboration_id", "url"},
            )
            value = self.controller.navigate(
                arguments.get("collaboration_id"),
                arguments.get("url"),
                ignore_cache=arguments.get("ignore_cache", False),
            )
        elif name == "browser_reload":
            self._require_arguments(
                arguments, {"collaboration_id", "ignore_cache"}, {"collaboration_id"}
            )
            value = self.controller.reload(
                arguments.get("collaboration_id"),
                ignore_cache=arguments.get("ignore_cache", False),
            )
        elif name == "browser_click":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator"},
                {"collaboration_id", "locator"},
            )
            value = self.controller.click(
                arguments.get("collaboration_id"), arguments.get("locator")
            )
        elif name == "browser_hover":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator"},
                {"collaboration_id", "locator"},
            )
            value = self.controller.hover(
                arguments.get("collaboration_id"), arguments.get("locator")
            )
        elif name == "browser_select":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator", "option_locator"},
                {"collaboration_id", "locator", "option_locator"},
            )
            value = self.controller.select(
                arguments.get("collaboration_id"),
                arguments.get("locator"),
                arguments.get("option_locator"),
            )
        elif name == "browser_drag":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator", "destination", "steps"},
                {"collaboration_id", "locator", "destination"},
            )
            value = self.controller.drag(
                arguments.get("collaboration_id"),
                arguments.get("locator"),
                arguments.get("destination"),
                steps=arguments.get("steps", 8),
            )
        elif name == "browser_type":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator", "text", "replace_all"},
                {"collaboration_id", "locator", "text"},
            )
            value = self.controller.type_text(
                arguments.get("collaboration_id"),
                arguments.get("locator"),
                arguments.get("text"),
                replace_all=arguments.get("replace_all", True),
            )
        elif name == "browser_key":
            self._require_arguments(
                arguments, {"collaboration_id", "keys"}, {"collaboration_id", "keys"}
            )
            value = self.controller.key_chord(
                arguments.get("collaboration_id"),
                arguments.get("keys"),
            )
        elif name == "browser_scroll":
            self._require_arguments(
                arguments,
                {"collaboration_id", "direction", "distance_px"},
                {"collaboration_id", "direction"},
            )
            value = self.controller.scroll(
                arguments.get("collaboration_id"),
                direction=arguments.get("direction"),
                distance_px=arguments.get("distance_px", 700),
            )
        elif name == "browser_scroll_to":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator"},
                {"collaboration_id", "locator"},
            )
            value = self.controller.scroll_to(
                arguments.get("collaboration_id"), arguments.get("locator")
            )
        elif name == "browser_dialog":
            self._require_arguments(
                arguments,
                {"collaboration_id", "accept", "prompt_text"},
                {"collaboration_id", "accept"},
            )
            value = self.controller.dialog(
                arguments.get("collaboration_id"),
                accept=arguments.get("accept"),
                prompt_text=arguments.get("prompt_text"),
            )
        elif name == "browser_upload":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator", "paths"},
                {"collaboration_id", "locator", "paths"},
            )
            value = self.controller.upload(
                arguments.get("collaboration_id"),
                arguments.get("locator"),
                arguments.get("paths"),
            )
        elif name == "browser_download":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator", "timeout_ms"},
                {"collaboration_id", "locator"},
            )
            value = self.controller.download(
                arguments.get("collaboration_id"),
                arguments.get("locator"),
                timeout_ms=arguments.get("timeout_ms", 30_000),
            )
        elif name == "browser_diagnostics":
            self._require_arguments(
                arguments, {"collaboration_id", "duration_ms"}, {"collaboration_id"}
            )
            value = self.controller.diagnostics(
                arguments.get("collaboration_id"),
                duration_ms=arguments.get("duration_ms", 1000),
            )
        elif name == "browser_credential_fill":
            self._require_arguments(
                arguments,
                {"collaboration_id", "locator", "broker"},
                {"collaboration_id", "locator", "broker"},
            )
            value = self.controller.credential_fill(
                arguments.get("collaboration_id"),
                arguments.get("locator"),
                broker=arguments.get("broker"),
            )
        elif name == "browser_record_start":
            self._require_arguments(arguments, set(), set())
            value = self.controller.recording_start()
        elif name == "browser_record_status":
            self._require_arguments(arguments, set(), set())
            value = self.controller.recording_status()
        elif name == "browser_record_stop":
            self._require_arguments(arguments, set(), set())
            value = self.controller.recording_stop()
        elif name == "browser_schedule_snapshot":
            self._require_arguments(
                arguments,
                {"collaboration_id", "delay_seconds", "max_items"},
                {"collaboration_id", "delay_seconds"},
            )
            value = self.controller.schedule_snapshot(
                arguments.get("collaboration_id"),
                delay_seconds=arguments.get("delay_seconds"),
                max_items=arguments.get("max_items", 400),
            )
        elif name == "browser_schedule_status":
            self._require_arguments(arguments, set(), set())
            value = self.controller.schedule_status()
        elif name == "browser_schedule_cancel":
            self._require_arguments(arguments, {"schedule_id"}, {"schedule_id"})
            value = self.controller.schedule_cancel(arguments.get("schedule_id"))
        elif name == "browser_schedule_result":
            self._require_arguments(arguments, {"schedule_id"}, {"schedule_id"})
            value = self.controller.schedule_result(arguments.get("schedule_id"))
        else:
            raise ValueError("unknown browser tool")
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
                    ),
                }
            ],
            "structuredContent": value,
            "isError": False,
        }

    @staticmethod
    def _require_arguments(
        arguments: dict[str, Any],
        allowed: set[str],
        required: set[str],
    ) -> None:
        if set(arguments).difference(allowed) or not required.issubset(arguments):
            raise ValueError("tool arguments have an invalid shape")

    def dispatch(self, request: Any) -> dict[str, Any] | None:
        if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
            return self._error(None, -32600, "Invalid Request")
        request_id = request.get("id")
        method = request.get("method")
        if not isinstance(method, str):
            return self._error(request_id, -32600, "Invalid Request")
        if request_id is None:
            return None
        try:
            if method == "initialize":
                parameters = request.get("params", {})
                requested = (
                    parameters.get("protocolVersion")
                    if isinstance(parameters, dict)
                    else None
                )
                return self._result(
                    request_id,
                    {
                        "protocolVersion": requested
                        if requested in SUPPORTED_MCP_PROTOCOLS
                        else MCP_PROTOCOL,
                        "capabilities": {"tools": {"listChanged": False}},
                        "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                    },
                )
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, {"tools": TOOLS})
            if method == "tools/call":
                parameters = request.get("params")
                if not isinstance(parameters, dict) or not isinstance(
                    parameters.get("name"), str
                ):
                    return self._error(request_id, -32602, "Invalid params")
                try:
                    result = self._tool_result(
                        parameters["name"], parameters.get("arguments", {})
                    )
                except BaseException as exc:
                    result = {
                        "content": [
                            {"type": "text", "text": collaboration_error_message(exc)}
                        ],
                        "isError": True,
                    }
                return self._result(request_id, result)
            if method in {"resources/list", "prompts/list"}:
                key = "resources" if method == "resources/list" else "prompts"
                return self._result(request_id, {key: []})
            return self._error(request_id, -32601, "Method not found")
        except BaseException:
            return self._error(request_id, -32603, "Internal error")

    @staticmethod
    def _result(request_id: Any, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    @staticmethod
    def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }

    def run(
        self,
        input_stream: BinaryIO | None = None,
        output_stream: BinaryIO | None = None,
    ) -> int:
        source = input_stream or sys.stdin.buffer
        destination = output_stream or sys.stdout.buffer
        while True:
            line = source.readline()
            if not line:
                return 0
            try:
                request = json.loads(line.decode("utf-8"))
                response = self.dispatch(request)
            except (UnicodeDecodeError, json.JSONDecodeError):
                response = self._error(None, -32700, "Parse error")
            if response is not None:
                destination.write(
                    json.dumps(response, sort_keys=True, separators=(",", ":")).encode(
                        "utf-8"
                    )
                    + b"\n"
                )
                destination.flush()


def run_mcp_server() -> int:
    return McpServer().run()
