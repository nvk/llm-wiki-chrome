from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from browser_executor.protocol import (
    ProtocolError,
    canonical_program_sha256,
    validate_program,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def resign(program: dict) -> dict:
    program["program_sha256"] = canonical_program_sha256(program)
    return program


class ProtocolTests(unittest.TestCase):
    def test_both_provider_spikes_validate(self) -> None:
        for name in ("google-docs-suggestions-v1.json", "x-space-read-v1.json"):
            with self.subTest(name=name):
                program = load_fixture(name)
                self.assertEqual(validate_program(program), program)
                self.assertEqual(canonical_program_sha256(program), program["program_sha256"])

    def test_canonical_hash_is_order_independent_and_excludes_hash_field(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        reordered = dict(reversed(list(program.items())))
        reordered["program_sha256"] = "f" * 64
        self.assertEqual(canonical_program_sha256(program), canonical_program_sha256(reordered))

    def test_arbitrary_execution_fields_are_rejected_at_any_depth(self) -> None:
        for key in ("javascript", "script", "expression", "runtime_evaluate", "cdp_method"):
            with self.subTest(key=key):
                program = load_fixture("x-space-read-v1.json")
                program["actions"][3]["locator"][key] = "synthetic"
                resign(program)
                with self.assertRaises(ProtocolError):
                    validate_program(program)

    def test_unknown_fields_fail_closed(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["ambient_browsing"] = True
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "unsupported fields"):
            validate_program(program)

    def test_program_hash_mismatch_fails_closed(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["target"]["url"] += "?changed=1"
        with self.assertRaisesRegex(ProtocolError, "program_sha256"):
            validate_program(program)

    def test_target_collaboration_origin_and_path_are_exact(self) -> None:
        variants = []
        base = load_fixture("x-space-read-v1.json")
        wrong_origin = copy.deepcopy(base)
        wrong_origin["target"]["origin"] = "https://example.invalid"
        variants.append(wrong_origin)
        wrong_path = copy.deepcopy(base)
        wrong_path["target"]["path_prefixes"] = ["/unrelated/"]
        variants.append(wrong_path)
        missing_collaboration = copy.deepcopy(base)
        del missing_collaboration["target"]["collaboration_id"]
        variants.append(missing_collaboration)
        invalid_collaboration = copy.deepcopy(base)
        invalid_collaboration["target"]["collaboration_id"] = "not-a-grant"
        variants.append(invalid_collaboration)
        for program in variants:
            resign(program)
            with self.assertRaises(ProtocolError):
                validate_program(program)

        user_exposed_origin = copy.deepcopy(base)
        user_exposed_origin["target"]["url"] = "https://example.invalid/synthetic#section"
        user_exposed_origin["target"]["origin"] = "https://example.invalid"
        user_exposed_origin["target"]["path_prefixes"] = ["/synthetic"]
        resign(user_exposed_origin)
        self.assertEqual(validate_program(user_exposed_origin), user_exposed_origin)

    def test_same_origin_navigation_is_bounded_to_target_paths(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"].insert(3, {
            "op": "navigate_same_origin",
            "url": program["target"]["url"] + "?synthetic=1",
        })
        resign(program)
        self.assertEqual(validate_program(program), program)

        invalid_urls = (
            "https://docs.google.com/document/d/SYNTHETIC_DOCUMENT/edit",
            "https://x.com/unrelated/SYNTHETIC",
            program["target"]["url"] + "_SIBLING",
            program["target"]["url"] + "#fragment",
        )
        for url in invalid_urls:
            invalid = copy.deepcopy(program)
            invalid["actions"][3]["url"] = url
            resign(invalid)
            with self.subTest(url=url), self.assertRaisesRegex(ProtocolError, "navigation URL"):
                validate_program(invalid)

    def test_lifecycle_and_mutation_boundary_must_be_top_level(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"] = [
            {"op": "open_or_focus_exact_url"},
            {"op": "first_success", "branches": [[{"op": "attach_debugger"}]]},
            {"op": "detach_debugger"},
        ]
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "lifecycle"):
            validate_program(program)

        program = load_fixture("google-docs-suggestions-v1.json")
        boundary = next(action for action in program["actions"] if action["op"] == "before_mutation")
        program["actions"].remove(boundary)
        program["actions"].insert(-1, {"op": "first_success", "branches": [[boundary]]})
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "mutation boundary"):
            validate_program(program)

    def test_locator_regex_subset_and_operation_shapes_fail_closed(self) -> None:
        for pattern in ("(", "(a+)+$", r"^value\\1$"):
            program = load_fixture("google-docs-suggestions-v1.json")
            program["actions"][13]["locator"]["name_matches"] = pattern
            resign(program)
            with self.subTest(pattern=pattern), self.assertRaisesRegex(ProtocolError, "name_matches"):
                validate_program(program)

        program = load_fixture("x-space-read-v1.json")
        program["actions"][3]["locator"]["visible"] = False
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "AX locators"):
            validate_program(program)

        program = load_fixture("x-space-read-v1.json")
        program["actions"][4]["branches"][1][0]["locator"]["role"] = "list"
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "DOM locators"):
            validate_program(program)

    def test_read_program_cannot_cross_mutation_boundary(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"].insert(-1, {"op": "before_mutation"})
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "read programs"):
            validate_program(program)

    def test_mutation_program_requires_exactly_one_boundary(self) -> None:
        program = load_fixture("google-docs-suggestions-v1.json")
        program["actions"] = [action for action in program["actions"] if action["op"] != "before_mutation"]
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "exactly one"):
            validate_program(program)

    def test_private_ax_snapshot_hash_is_bounded_and_declared(self) -> None:
        program = load_fixture("google-docs-suggestions-v1.json")
        program["private_slots"].append("baseline.sha256")
        program["actions"].insert(3, {
            "op": "assert_ax_private_sha256",
            "slot": "baseline.sha256",
            "locator": {"name_matches": ".+"},
            "fields": ["role", "name", "value"],
            "max_items": 5000,
        })
        program["limits"]["max_actions"] += 1
        resign(program)
        self.assertEqual(validate_program(program), program)

        undeclared = copy.deepcopy(program)
        undeclared["actions"][3]["slot"] = "other.sha256"
        resign(undeclared)
        with self.assertRaisesRegex(ProtocolError, "undeclared private slot"):
            validate_program(undeclared)

        oversized = copy.deepcopy(program)
        oversized["actions"][3]["max_items"] = 5001
        resign(oversized)
        with self.assertRaisesRegex(ProtocolError, "max_items"):
            validate_program(oversized)

    def test_private_value_wait_is_bounded_and_declared(self) -> None:
        program = load_fixture("google-docs-suggestions-v1.json")
        waits = [
            action for action in program["actions"]
            if action["op"] == "wait_ax_private_value"
        ]
        self.assertEqual(len(waits), 2)
        self.assertEqual(validate_program(program), program)

        undeclared = copy.deepcopy(program)
        next(
            action for action in undeclared["actions"]
            if action["op"] == "wait_ax_private_value"
        )["slot"] = "edit.undeclared"
        resign(undeclared)
        with self.assertRaisesRegex(ProtocolError, "undeclared private slot"):
            validate_program(undeclared)

        for value in (49, 300001, True):
            invalid = copy.deepcopy(program)
            next(
                action for action in invalid["actions"]
                if action["op"] == "wait_ax_private_value"
            )["timeout_ms"] = value
            resign(invalid)
            with self.subTest(timeout_ms=value), self.assertRaisesRegex(ProtocolError, "timeout_ms"):
                validate_program(invalid)

    def test_action_count_includes_bounded_branches(self) -> None:
        program = load_fixture("google-docs-suggestions-v1.json")
        program["limits"]["max_actions"] = 3
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "max_actions"):
            validate_program(program)

    def test_extraction_limit_and_result_declarations_are_bounded(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"][-3]["max_items"] = 5001
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "max_items"):
            validate_program(program)

    def test_private_viewport_capture_is_declared_and_bounded(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"].insert(-1, {
            "op": "capture_viewport_private",
            "private_result": "space.viewport",
            "quality": 70,
            "max_bytes": 262144,
        })
        program["result"]["private_fields"].append("space.viewport")
        resign(program)
        self.assertEqual(validate_program(program), program)

        for field, value in (("quality", 91), ("max_bytes", 262145)):
            invalid = copy.deepcopy(program)
            invalid["actions"][-2][field] = value
            resign(invalid)
            with self.subTest(field=field), self.assertRaisesRegex(ProtocolError, "screenshot"):
                validate_program(invalid)

        program = load_fixture("x-space-read-v1.json")
        program["result"]["private_fields"].append("space.unused")
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "exactly match"):
            validate_program(program)

    def test_viewport_scroll_and_private_link_fields_are_bounded(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"].insert(2, {
            "op": "scroll_viewport",
            "direction": "down",
            "distance_px": 640,
        })
        extraction = next(action for action in program["actions"] if action["op"] == "extract_ax")
        extraction["fields"] = ["name", "description", "url"]
        resign(program)
        self.assertEqual(validate_program(program), program)

        for action in (
            {"op": "scroll_viewport", "direction": "sideways", "distance_px": 640},
            {"op": "scroll_viewport", "direction": "down", "distance_px": 10001},
            {"op": "scroll_viewport", "direction": "down", "distance_px": True},
        ):
            invalid = load_fixture("x-space-read-v1.json")
            invalid["actions"].insert(2, action)
            resign(invalid)
            with self.subTest(action=action), self.assertRaises(ProtocolError):
                validate_program(invalid)

    def test_scrolling_collection_bounds_and_dedupe_are_validated(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        extraction = next(
            action for action in program["actions"] if action["op"] == "extract_ax_collection"
        )
        extraction.update({
            "op": "collect_ax_by_scrolling",
            "direction": "down",
            "distance_px": 640,
            "max_scrolls": 6,
            "settle_ms": 250,
            "dedupe_fields": ["name"],
            "stable_rounds": 2,
            "scroll_anchor": {
                "roles": ["dialog", "list"],
                "name_contains_any": ["people", "listeners", "participants"],
                "unique": True,
            },
        })
        resign(program)
        self.assertEqual(validate_program(program), program)

        changes = (
            {"max_scrolls": 7},
            {"stable_rounds": 3, "max_scrolls": 2},
            {"dedupe_fields": ["url"]},
            {"settle_ms": True},
            {"scroll_anchor": {"selector": "#synthetic"}},
        )
        for change in changes:
            invalid = copy.deepcopy(program)
            action = next(
                item for item in invalid["actions"] if item["op"] == "collect_ax_by_scrolling"
            )
            action.update(change)
            resign(invalid)
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                validate_program(invalid)

    def test_private_browser_log_capture_is_paired_and_bounded(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"].insert(3, {
            "op": "start_log_capture",
            "private_result": "space.browser-log",
            "max_entries": 50,
            "max_text_bytes": 4096,
        })
        program["actions"].insert(-1, {"op": "stop_log_capture"})
        program["result"]["private_fields"].append("space.browser-log")
        resign(program)
        self.assertEqual(validate_program(program), program)

        for change in (
            {"max_entries": 501},
            {"max_text_bytes": 255},
            {"max_entries": True},
        ):
            invalid = copy.deepcopy(program)
            start = next(action for action in invalid["actions"] if action["op"] == "start_log_capture")
            start.update(change)
            resign(invalid)
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                validate_program(invalid)

        missing_stop = copy.deepcopy(program)
        missing_stop["actions"] = [
            action for action in missing_stop["actions"] if action["op"] != "stop_log_capture"
        ]
        resign(missing_stop)
        with self.assertRaisesRegex(ProtocolError, "lifecycle"):
            validate_program(missing_stop)

    def test_private_request_capture_is_paired_and_bounded(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"].insert(3, {
            "op": "start_request_capture",
            "private_result": "space.requests",
            "max_entries": 50,
            "max_url_bytes": 4096,
        })
        program["actions"].insert(-1, {"op": "stop_request_capture"})
        program["result"]["private_fields"].append("space.requests")
        resign(program)
        self.assertEqual(validate_program(program), program)

        for change in (
            {"max_entries": 501},
            {"max_url_bytes": 255},
            {"max_entries": True},
        ):
            invalid = copy.deepcopy(program)
            start = next(
                action for action in invalid["actions"]
                if action["op"] == "start_request_capture"
            )
            start.update(change)
            resign(invalid)
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                validate_program(invalid)

        nested_stop = copy.deepcopy(program)
        nested_stop["actions"] = [
            action for action in nested_stop["actions"]
            if action["op"] != "stop_request_capture"
        ]
        nested_stop["actions"].insert(-1, {
            "op": "first_success",
            "branches": [[{"op": "stop_request_capture"}]],
        })
        resign(nested_stop)
        with self.assertRaisesRegex(ProtocolError, "lifecycle"):
            validate_program(nested_stop)

    def test_private_console_capture_is_paired_and_bounded(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"].insert(3, {
            "op": "start_console_capture",
            "private_result": "space.console",
            "max_entries": 50,
            "max_arguments": 10,
            "max_argument_bytes": 4096,
        })
        program["actions"].insert(-1, {"op": "stop_console_capture"})
        program["result"]["private_fields"].append("space.console")
        resign(program)
        self.assertEqual(validate_program(program), program)

        for change in (
            {"max_entries": 501},
            {"max_arguments": 21},
            {"max_argument_bytes": 255},
            {"max_arguments": True},
        ):
            invalid = copy.deepcopy(program)
            start = next(
                action for action in invalid["actions"]
                if action["op"] == "start_console_capture"
            )
            start.update(change)
            resign(invalid)
            with self.subTest(change=change), self.assertRaises(ProtocolError):
                validate_program(invalid)

        missing_stop = copy.deepcopy(program)
        missing_stop["actions"] = [
            action for action in missing_stop["actions"]
            if action["op"] != "stop_console_capture"
        ]
        resign(missing_stop)
        with self.assertRaisesRegex(ProtocolError, "lifecycle"):
            validate_program(missing_stop)

    def test_nested_branches_are_bounded(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        nested = {"op": "first_success", "branches": [[{"op": "assert_exact_target"}]]}
        cursor = nested
        for _ in range(5):
            child = {"op": "first_success", "branches": [[{"op": "assert_exact_target"}]]}
            cursor["branches"] = [[child]]
            cursor = child
        program["actions"] = [nested]
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "nesting"):
            validate_program(program)

    def test_empty_branch_and_boolean_limits_fail_as_protocol_errors(self) -> None:
        program = load_fixture("x-space-read-v1.json")
        program["actions"][4]["branches"] = []
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "one to four"):
            validate_program(program)

        program = load_fixture("x-space-read-v1.json")
        program["limits"]["max_actions"] = True
        resign(program)
        with self.assertRaises(ProtocolError):
            validate_program(program)

    def test_schemas_are_parseable_and_protocol_versioned(self) -> None:
        job = json.loads((ROOT / "schemas" / "job-v1.schema.json").read_text(encoding="utf-8"))
        result = json.loads((ROOT / "schemas" / "result-v1.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(job["properties"]["protocol"]["const"], "llm-wiki-browser-executor/v1")
        self.assertEqual(result["properties"]["protocol"]["const"], "llm-wiki-browser-executor/v1")


if __name__ == "__main__":
    unittest.main()
