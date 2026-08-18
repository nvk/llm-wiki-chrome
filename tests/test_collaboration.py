from __future__ import annotations

import unittest
from typing import Any, Callable

from browser_executor.collaboration import (
    MAX_ACTIVE_SCHEDULES,
    MAX_RETAINED_SCHEDULES,
    BrowserCollaborationController,
    CollaborationError,
)
from browser_executor.protocol import validate_program


class FakeClient:
    def __init__(self) -> None:
        self.shared = [
            {
                "collaboration_id": "a" * 64,
                "url": "https://example.invalid/private?synthetic=1",
                "origin": "https://example.invalid",
            }
        ]
        self.calls: list[dict[str, Any]] = []

    def collaborations(self) -> list[dict[str, str]]:
        return [dict(value) for value in self.shared]

    def collaboration_for_url(self, url: str) -> dict[str, str] | None:
        values = [value for value in self.shared if value["url"] == url]
        return dict(values[0]) if len(values) == 1 else None

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
        self.calls.append(
            {
                "program": validated,
                "private_values": private_values or {},
                "has_boundary": before_mutation is not None,
            }
        )
        for action in validated["actions"]:
            if action["op"] in {"create_same_origin_tab", "navigate_same_origin"}:
                value = {
                    "collaboration_id": "b" * 64,
                    "url": action["url"],
                    "origin": "https://example.invalid",
                }
                if action["op"] == "create_same_origin_tab":
                    self.shared.append(value)
                else:
                    self.shared[0] = value
            if action["op"] == "navigate_history":
                self.shared[0] = {
                    "collaboration_id": "b" * 64,
                    "url": action["expected_url"],
                    "origin": "https://example.invalid",
                }
        private: dict[str, Any] = {}
        if "page.ax" in validated["result"]["private_fields"]:
            private["page.ax"] = [{"role": "heading", "name": "Synthetic"}]
        if "page.viewport" in validated["result"]["private_fields"]:
            private["page.viewport"] = {
                "mime_type": "image/jpeg",
                "data_base64": "c3ludGhldGlj",
            }
        for field in validated["result"]["private_fields"]:
            if field in {"page.region", "page.full"}:
                private[field] = {
                    "mime_type": "image/jpeg",
                    "data_base64": "c3ludGhldGlj",
                }
            elif field == "page.geometry":
                private[field] = [
                    {
                        "name": "Synthetic",
                        "role": "button",
                        "x": 1,
                        "y": 2,
                        "width": 3,
                        "height": 4,
                    }
                ]
            elif field.startswith("diagnostics."):
                private[field] = (
                    []
                    if field.endswith("performance")
                    else {"entries": [], "truncated": False}
                )
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
        self.assertEqual(
            self.controller.status(),
            {
                "connected": True,
                "shared_tabs": 1,
                "ready": True,
            },
        )

    def test_snapshot_compiles_one_exact_read_program(self) -> None:
        result = self.controller.snapshot(self.collaboration_id, max_items=300)
        self.assertEqual(result["nodes"], [{"role": "heading", "name": "Synthetic"}])
        call = self.client.calls[-1]
        program = call["program"]
        self.assertEqual(program["capability"], "read")
        self.assertEqual(program["target"]["collaboration_id"], self.collaboration_id)
        self.assertEqual(program["target"]["url"], self.client.shared[0]["url"])
        self.assertEqual(program["target"]["path_prefixes"], ["/"])
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
        self.controller.scroll_to(
            self.collaboration_id, {"role": "button", "name": "Synthetic"}
        )
        self.assertEqual(self.client.calls[-1]["program"]["capability"], "read")
        self.controller.key_chord(self.collaboration_id, ["platform-primary", "l"])
        self.assertEqual(self.client.calls[-1]["program"]["capability"], "mutation")
        self.assertEqual(self.authorization_count, 1)
        self.controller.dialog(self.collaboration_id, accept=False)
        self.assertEqual(self.client.calls[-1]["program"]["capability"], "mutation")
        self.assertEqual(self.authorization_count, 2)

    def test_rejects_unshared_ids_css_and_unsafe_locators(self) -> None:
        with self.assertRaisesRegex(CollaborationError, "no longer active"):
            self.controller.snapshot("b" * 64)
        with self.assertRaisesRegex(CollaborationError, "unsupported fields"):
            self.controller.click(self.collaboration_id, {"selector": "#danger"})
        with self.assertRaisesRegex(CollaborationError, "semantic identity"):
            self.controller.click(self.collaboration_id, {"ordinal": 0})

    def test_navigation_tab_lifecycle_and_advanced_interactions_are_typed(self) -> None:
        opened = self.controller.open(
            self.collaboration_id, "https://example.invalid/second"
        )
        self.assertEqual(opened["tab"]["collaboration_id"], "b" * 64)
        self.assertIn(
            "create_same_origin_tab",
            [action["op"] for action in self.client.calls[-1]["program"]["actions"]],
        )
        self.client.shared = [self.client.shared[0]]
        navigated = self.controller.navigate(
            self.collaboration_id, "https://example.invalid/next"
        )
        self.assertEqual(navigated["tab"]["url"], "https://example.invalid/next")
        next_id = navigated["tab"]["collaboration_id"]
        self.controller.hover(next_id, {"role": "button", "name": "Synthetic"})
        self.assertEqual(self.client.calls[-1]["program"]["capability"], "read")
        self.controller.drag(
            next_id,
            {"role": "button", "name": "Synthetic"},
            {"role": "region", "name": "Destination"},
            steps=6,
        )
        self.assertEqual(self.client.calls[-1]["program"]["capability"], "mutation")

    def test_visual_diagnostics_and_reviewed_recording_are_private(self) -> None:
        self.controller.recording_start()
        self.controller.hover(
            self.collaboration_id, {"role": "button", "name": "Synthetic"}
        )
        draft = self.controller.recording_stop()
        self.assertTrue(draft["review_required"])
        self.assertFalse(draft["replayable"])
        self.assertEqual(len(draft["sha256"]), 64)
        capture = self.controller.region_screenshot(
            self.collaboration_id,
            x=0,
            y=0,
            width=100,
            height=100,
        )
        self.assertEqual(capture["mime_type"], "image/jpeg")
        geometry = self.controller.geometry(
            self.collaboration_id,
            {"role": "button", "name": "Synthetic"},
        )
        self.assertEqual(geometry["items"][0]["width"], 3)
        diagnostics = self.controller.diagnostics(self.collaboration_id, duration_ms=20)
        self.assertIn("diagnostics.performance", diagnostics)

    def test_read_only_schedule_is_bounded_content_free_and_cancellable(self) -> None:
        scheduled = self.controller.schedule_snapshot(
            self.collaboration_id, delay_seconds=60, max_items=10
        )
        status = self.controller.schedule_status()
        self.assertEqual(status["schedules"][0]["state"], "scheduled")
        self.assertNotIn("url", status["schedules"][0])
        cancelled = self.controller.schedule_cancel(scheduled["schedule_id"])
        self.assertEqual(cancelled["status"], "cancelled")

    def test_schedule_registration_is_bounded(self) -> None:
        active = [
            self.controller.schedule_snapshot(self.collaboration_id, delay_seconds=3600)
            for _ in range(MAX_ACTIVE_SCHEDULES)
        ]
        with self.assertRaisesRegex(CollaborationError, "too many active"):
            self.controller.schedule_snapshot(self.collaboration_id, delay_seconds=3600)
        for item in active:
            self.controller.schedule_cancel(item["schedule_id"])

        retained = 0
        while len(self.controller._schedules) < MAX_RETAINED_SCHEDULES:
            scheduled = self.controller.schedule_snapshot(
                self.collaboration_id, delay_seconds=3600
            )
            job = self.controller._schedules[scheduled["schedule_id"]]
            job["timer"].cancel()
            job["state"] = "failed"
            retained += 1
        self.assertEqual(retained, MAX_RETAINED_SCHEDULES - MAX_ACTIVE_SCHEDULES)
        self.assertLessEqual(len(self.controller._schedules), MAX_RETAINED_SCHEDULES)

        failed = [
            key
            for key, job in self.controller._schedules.items()
            if job["state"] == "failed"
        ]
        for key in failed[: MAX_ACTIVE_SCHEDULES - 1]:
            self.controller._schedules[key]["state"] = "scheduled"
        scheduled = self.controller.schedule_snapshot(
            self.collaboration_id, delay_seconds=3600
        )
        with self.assertRaisesRegex(CollaborationError, "too many active"):
            self.controller.schedule_snapshot(self.collaboration_id, delay_seconds=3600)
        for key, job in self.controller._schedules.items():
            job["timer"].cancel()

    def test_completed_schedule_retention_is_bounded(self) -> None:
        schedule_ids = []
        for _ in range(MAX_RETAINED_SCHEDULES):
            scheduled = self.controller.schedule_snapshot(
                self.collaboration_id, delay_seconds=3600
            )
            schedule_id = scheduled["schedule_id"]
            schedule_ids.append(schedule_id)
            job = self.controller._schedules[schedule_id]
            job["timer"].cancel()
            job["state"] = "complete"
            job["result"] = {"synthetic": True}

        with self.assertRaisesRegex(CollaborationError, "await retrieval"):
            self.controller.schedule_snapshot(
                self.collaboration_id, delay_seconds=3600
            )

        retrieved = self.controller.schedule_result(schedule_ids[0])
        self.assertEqual(retrieved["state"], "complete")
        replacement = self.controller.schedule_snapshot(
            self.collaboration_id, delay_seconds=3600
        )
        self.controller.schedule_cancel(replacement["schedule_id"])


if __name__ == "__main__":
    unittest.main()
