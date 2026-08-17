from __future__ import annotations

import unittest
from typing import Any, Callable

from browser_executor.collaboration import (
    BrowserCollaborationController,
    CollaborationError,
)
from browser_executor.protocol import validate_program


class FakeClient:
    def __init__(self) -> None:
        self.shared = [{
            "collaboration_id": "a" * 64,
            "url": "https://example.invalid/private?synthetic=1",
            "origin": "https://example.invalid",
        }]
        self.calls: list[dict[str, Any]] = []

    def collaborations(self) -> list[dict[str, str]]:
        return [dict(value) for value in self.shared]

    def run(
        self,
        program: dict[str, Any],
        *,
        private_values: dict[str, str] | None = None,
        before_mutation: Callable[[], None] | None = None,
    ) -> dict[str, Any]:
        validated = validate_program(program)
        if before_mutation is not None:
            before_mutation()
        self.calls.append({
            "program": validated,
            "private_values": private_values or {},
            "has_boundary": before_mutation is not None,
        })
        private: dict[str, Any] = {}
        if "page.ax" in validated["result"]["private_fields"]:
            private["page.ax"] = [{"role": "heading", "name": "Synthetic"}]
        if "page.viewport" in validated["result"]["private_fields"]:
            private["page.viewport"] = {"mime_type": "image/jpeg", "data_base64": "c3ludGhldGlj"}
        return {
            "status": "ok",
            "public": {
                "status": "ok",
                "action_count": len(validated["actions"]),
                "mutation_started": before_mutation is not None,
                "private_result_count": len(private),
            },
            "private": private,
        }


class CollaborationControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeClient()
        self.authorization_count = 0

        def authorize() -> None:
            self.authorization_count += 1

        self.controller = BrowserCollaborationController(self.client, authorize)
        self.collaboration_id = "a" * 64

    def test_lists_only_explicit_click_grants(self) -> None:
        self.assertEqual(self.controller.tabs(), self.client.shared)

    def test_snapshot_compiles_one_exact_read_program(self) -> None:
        result = self.controller.snapshot(self.collaboration_id, max_items=300)
        self.assertEqual(result["nodes"], [{"role": "heading", "name": "Synthetic"}])
        call = self.client.calls[-1]
        program = call["program"]
        self.assertEqual(program["capability"], "read")
        self.assertEqual(program["target"]["collaboration_id"], self.collaboration_id)
        self.assertEqual(program["target"]["url"], self.client.shared[0]["url"])
        self.assertEqual(program["target"]["path_prefixes"], ["/private"])
        self.assertNotIn("selector", str(program))
        self.assertFalse(call["has_boundary"])

    def test_screenshot_stays_a_private_executor_result(self) -> None:
        result = self.controller.screenshot(self.collaboration_id)
        self.assertEqual(result["mime_type"], "image/jpeg")
        program = self.client.calls[-1]["program"]
        self.assertEqual(program["result"]["private_fields"], ["page.viewport"])
        self.assertNotIn("page.viewport", program["result"]["public_fields"])

    def test_click_uses_one_internal_mutation_boundary(self) -> None:
        result = self.controller.click(
            self.collaboration_id,
            {"role": "button", "name": "Synthetic", "unique": True},
        )
        self.assertTrue(result["mutation_started"])
        self.assertEqual(self.authorization_count, 1)
        program = self.client.calls[-1]["program"]
        self.assertEqual(program["capability"], "mutation")
        self.assertEqual(
            [action["op"] for action in program["actions"]].count("before_mutation"),
            1,
        )

    def test_private_typed_text_is_not_embedded_in_the_program(self) -> None:
        secret = "synthetic private input"
        self.controller.type_text(
            self.collaboration_id,
            {"role": "textbox", "name": "Search", "unique": True},
            secret,
        )
        call = self.client.calls[-1]
        self.assertNotIn(secret, str(call["program"]))
        self.assertEqual(call["private_values"], {"input.text": secret})
        self.assertEqual(self.authorization_count, 1)

    def test_scroll_is_read_only_and_key_chord_is_governed(self) -> None:
        self.controller.scroll(self.collaboration_id, direction="down", distance_px=500)
        self.assertEqual(self.client.calls[-1]["program"]["capability"], "read")
        self.controller.key_chord(self.collaboration_id, ["platform-primary", "l"])
        self.assertEqual(self.client.calls[-1]["program"]["capability"], "mutation")
        self.assertEqual(self.authorization_count, 1)

    def test_rejects_unshared_ids_css_and_unsafe_locators(self) -> None:
        with self.assertRaisesRegex(CollaborationError, "no longer active"):
            self.controller.snapshot("b" * 64)
        with self.assertRaisesRegex(CollaborationError, "unsupported fields"):
            self.controller.click(self.collaboration_id, {"selector": "#danger"})
        with self.assertRaisesRegex(CollaborationError, "semantic identity"):
            self.controller.click(self.collaboration_id, {"ordinal": 0})


if __name__ == "__main__":
    unittest.main()
