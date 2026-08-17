from __future__ import annotations

import json
import sys
from typing import Any, BinaryIO

from .collaboration import BrowserCollaborationController, collaboration_error_message

MCP_PROTOCOL = "2025-06-18"
SUPPORTED_MCP_PROTOCOLS = {MCP_PROTOCOL, "2025-11-25"}
SERVER_NAME = "llm-wiki-browser-collaboration"
SERVER_VERSION = "0.0.1"


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
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
        "roles": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 8},
        "name": {"type": "string"},
        "name_contains": {"type": "string"},
        "name_contains_any": {
            "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 12,
        },
        "name_matches": {"type": "string"},
        "within": {"type": "object"},
        "within_name_contains_any": {
            "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 12,
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
        "name": "browser_snapshot",
        "description": "Read a bounded accessibility-tree projection from one explicitly shared tab.",
        "inputSchema": _object_schema({
            "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "max_items": {"type": "integer", "minimum": 1, "maximum": 1500, "default": 400},
        }, ["collaboration_id"]),
    },
    {
        "name": "browser_screenshot",
        "description": "Capture the current viewport of one explicitly shared tab as a private JPEG result.",
        "inputSchema": _object_schema({
            "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "quality": {"type": "integer", "minimum": 10, "maximum": 90, "default": 65},
        }, ["collaboration_id"]),
    },
    {
        "name": "browser_click",
        "description": "Click one uniquely identified accessibility-tree control in an explicitly shared tab.",
        "inputSchema": _object_schema({
            "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "locator": LOCATOR_SCHEMA,
        }, ["collaboration_id", "locator"]),
    },
    {
        "name": "browser_type",
        "description": (
            "Focus one semantic control and insert private text in an explicitly shared tab; "
            "this does not submit the form."
        ),
        "inputSchema": _object_schema({
            "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "locator": LOCATOR_SCHEMA,
            "text": {"type": "string", "minLength": 1, "maxLength": 16384},
            "replace_all": {"type": "boolean", "default": True},
        }, ["collaboration_id", "locator", "text"]),
    },
    {
        "name": "browser_key",
        "description": (
            "Dispatch one bounded key chord to an explicitly shared tab. Modifier and Enter/Tab chords "
            "can commit or submit a focused form; this crosses the governed mutation boundary."
        ),
        "inputSchema": _object_schema({
            "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "keys": {
                "type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 5,
            },
        }, ["collaboration_id", "keys"]),
    },
    {
        "name": "browser_scroll",
        "description": "Scroll the viewport of one explicitly shared tab by a bounded distance.",
        "inputSchema": _object_schema({
            "collaboration_id": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            "direction": {"type": "string", "enum": ["up", "down"]},
            "distance_px": {"type": "integer", "minimum": 1, "maximum": 10000, "default": 700},
        }, ["collaboration_id", "direction"]),
    },
]


class McpServer:
    def __init__(self, controller: BrowserCollaborationController | None = None) -> None:
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
        elif name == "browser_snapshot":
            self._require_arguments(arguments, {"collaboration_id", "max_items"}, {"collaboration_id"})
            value = self.controller.snapshot(
                arguments.get("collaboration_id"),
                max_items=arguments.get("max_items", 400),
            )
        elif name == "browser_screenshot":
            self._require_arguments(arguments, {"collaboration_id", "quality"}, {"collaboration_id"})
            value = self.controller.screenshot(
                arguments.get("collaboration_id"),
                quality=arguments.get("quality", 65),
            )
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({
                            "status": "ok",
                            "collaboration_id": value["collaboration_id"],
                            "url": value["url"],
                        }, sort_keys=True, separators=(",", ":")),
                    },
                    {
                        "type": "image",
                        "data": value["data_base64"],
                        "mimeType": value["mime_type"],
                    },
                ],
                "isError": False,
            }
        elif name == "browser_click":
            self._require_arguments(arguments, {"collaboration_id", "locator"}, {"collaboration_id", "locator"})
            value = self.controller.click(arguments.get("collaboration_id"), arguments.get("locator"))
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
            self._require_arguments(arguments, {"collaboration_id", "keys"}, {"collaboration_id", "keys"})
            value = self.controller.key_chord(
                arguments.get("collaboration_id"), arguments.get("keys"),
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
        else:
            raise ValueError("unknown browser tool")
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
            }],
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
                requested = parameters.get("protocolVersion") if isinstance(parameters, dict) else None
                return self._result(request_id, {
                    "protocolVersion": requested if requested in SUPPORTED_MCP_PROTOCOLS else MCP_PROTOCOL,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                })
            if method == "ping":
                return self._result(request_id, {})
            if method == "tools/list":
                return self._result(request_id, {"tools": TOOLS})
            if method == "tools/call":
                parameters = request.get("params")
                if not isinstance(parameters, dict) or not isinstance(parameters.get("name"), str):
                    return self._error(request_id, -32602, "Invalid params")
                try:
                    result = self._tool_result(parameters["name"], parameters.get("arguments", {}))
                except BaseException as exc:
                    result = {
                        "content": [{"type": "text", "text": collaboration_error_message(exc)}],
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

    def run(self, input_stream: BinaryIO | None = None, output_stream: BinaryIO | None = None) -> int:
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
                    json.dumps(response, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
                )
                destination.flush()


def run_mcp_server() -> int:
    return McpServer().run()
