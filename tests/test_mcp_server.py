from __future__ import annotations

import io
import json
import unittest
from typing import Any

from browser_executor.mcp_server import McpServer, TOOLS


class FakeController:
    def status(self) -> dict[str, Any]:
        return {"connected": True, "shared_tabs": 1, "ready": True}

    def tabs(self) -> list[dict[str, str]]:
        return [
            {
                "collaboration_id": "a" * 64,
                "url": "https://example.invalid/synthetic",
                "origin": "https://example.invalid",
            }
        ]

    def snapshot(self, collaboration_id: str, *, max_items: int) -> dict[str, Any]:
        return {"collaboration_id": collaboration_id, "nodes": [{"name": "Synthetic"}]}

    def screenshot(self, collaboration_id: str, *, quality: int) -> dict[str, Any]:
        return {
            "collaboration_id": collaboration_id,
            "url": "https://example.invalid/synthetic",
            "mime_type": "image/jpeg",
            "data_base64": "c3ludGhldGlj",
        }

    def click(self, collaboration_id: str, locator: Any) -> dict[str, Any]:
        return {"status": "ok", "collaboration_id": collaboration_id}

    def type_text(
        self,
        collaboration_id: str,
        locator: Any,
        text: Any,
        *,
        replace_all: bool,
    ) -> dict[str, Any]:
        return {"status": "ok", "collaboration_id": collaboration_id}

    def key_chord(self, collaboration_id: str, keys: Any) -> dict[str, Any]:
        return {"status": "ok", "collaboration_id": collaboration_id}

    def scroll(
        self, collaboration_id: str, *, direction: str, distance_px: int
    ) -> dict[str, Any]:
        return {"status": "ok", "collaboration_id": collaboration_id}


class McpServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = McpServer(FakeController())

    @staticmethod
    def request(
        method: str, params: dict[str, Any] | None = None, request_id: int = 1
    ) -> dict[str, Any]:
        value: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            value["params"] = params
        return value

    def test_initialize_and_tool_inventory(self) -> None:
        initialized = self.server.dispatch(
            self.request(
                "initialize",
                {"protocolVersion": "2025-06-18"},
            )
        )
        self.assertEqual(initialized["result"]["protocolVersion"], "2025-06-18")
        listed = self.server.dispatch(self.request("tools/list"))
        names = [tool["name"] for tool in listed["result"]["tools"]]
        self.assertEqual(
            names,
            [
                "browser_status",
                "browser_tabs",
                "browser_focus",
                "browser_open",
                "browser_history",
                "browser_close",
                "browser_snapshot",
                "browser_screenshot",
                "browser_region_screenshot",
                "browser_full_page_screenshot",
                "browser_geometry",
                "browser_wait",
                "browser_navigate",
                "browser_reload",
                "browser_click",
                "browser_hover",
                "browser_select",
                "browser_drag",
                "browser_type",
                "browser_key",
                "browser_scroll",
                "browser_scroll_to",
                "browser_dialog",
                "browser_upload",
                "browser_download",
                "browser_diagnostics",
                "browser_credential_fill",
                "browser_record_start",
                "browser_record_status",
                "browser_record_stop",
                "browser_schedule_snapshot",
                "browser_schedule_status",
                "browser_schedule_cancel",
                "browser_schedule_result",
            ],
        )
        self.assertNotIn("javascript", json.dumps(TOOLS).lower())
        self.assertNotIn("program", names)

    def test_tabs_and_snapshot_return_private_runtime_content_to_caller(self) -> None:
        status = self.server.dispatch(
            self.request(
                "tools/call",
                {
                    "name": "browser_status",
                    "arguments": {},
                },
            )
        )
        self.assertTrue(status["result"]["structuredContent"]["ready"])
        tabs = self.server.dispatch(
            self.request(
                "tools/call",
                {
                    "name": "browser_tabs",
                    "arguments": {},
                },
            )
        )
        self.assertEqual(
            tabs["result"]["structuredContent"]["tabs"][0]["origin"],
            "https://example.invalid",
        )
        snapshot = self.server.dispatch(
            self.request(
                "tools/call",
                {
                    "name": "browser_snapshot",
                    "arguments": {"collaboration_id": "a" * 64},
                },
            )
        )
        self.assertEqual(
            snapshot["result"]["structuredContent"]["nodes"][0]["name"], "Synthetic"
        )

    def test_screenshot_returns_an_mcp_image_block(self) -> None:
        response = self.server.dispatch(
            self.request(
                "tools/call",
                {
                    "name": "browser_screenshot",
                    "arguments": {"collaboration_id": "a" * 64},
                },
            )
        )
        image = response["result"]["content"][1]
        self.assertEqual(
            image,
            {
                "type": "image",
                "data": "c3ludGhldGlj",
                "mimeType": "image/jpeg",
            },
        )

    def test_stdio_is_newline_delimited_json_rpc_without_extra_output(self) -> None:
        source = io.BytesIO(
            json.dumps(self.request("ping")).encode("utf-8")
            + b"\n"
            + json.dumps(self.request("tools/list", request_id=2)).encode("utf-8")
            + b"\n"
        )
        destination = io.BytesIO()
        self.assertEqual(self.server.run(source, destination), 0)
        lines = destination.getvalue().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["result"], {})
        self.assertEqual(len(json.loads(lines[1])["result"]["tools"]), len(TOOLS))

    def test_tool_failures_use_is_error_without_json_rpc_failure_details(self) -> None:
        response = self.server.dispatch(
            self.request(
                "tools/call",
                {
                    "name": "unknown",
                    "arguments": {},
                },
            )
        )
        self.assertTrue(response["result"]["isError"])
        self.assertEqual(
            response["result"]["content"][0]["text"], "browser collaboration failed"
        )

        extra = self.server.dispatch(
            self.request(
                "tools/call",
                {
                    "name": "browser_tabs",
                    "arguments": {"program": "not accepted"},
                },
            )
        )
        self.assertTrue(extra["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
