from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from browser_executor.protocol import ProtocolError, canonical_program_sha256, validate_program


ROOT = Path(__file__).resolve().parents[1]


def fixture(name: str) -> dict:
    return json.loads((ROOT / "tests" / "fixtures" / name).read_text(encoding="utf-8"))


def resign(program: dict) -> dict:
    program["program_sha256"] = canonical_program_sha256(program)
    return program


@unittest.skipUnless(shutil.which("node"), "Node is required for cross-language validation")
class CrossLanguageProtocolTests(unittest.TestCase):
    def test_python_and_extension_make_the_same_policy_decisions(self) -> None:
        base = fixture("x-space-read-v1.json")
        cases: list[dict] = [base, fixture("google-docs-suggestions-v1.json")]

        scroll_and_link = copy.deepcopy(base)
        scroll_and_link["actions"].insert(2, {
            "op": "scroll_viewport", "direction": "down", "distance_px": 640,
        })
        extraction = next(
            action for action in scroll_and_link["actions"] if action["op"] == "extract_ax"
        )
        extraction["fields"] = ["name", "description", "url"]
        cases.append(resign(scroll_and_link))

        scrolling_collection = copy.deepcopy(base)
        attendees = next(
            action for action in scrolling_collection["actions"]
            if action["op"] == "extract_ax_collection"
        )
        attendees.update({
            "op": "collect_ax_by_scrolling",
            "direction": "down",
            "distance_px": 640,
            "max_scrolls": 4,
            "settle_ms": 250,
            "dedupe_fields": ["name"],
            "stable_rounds": 2,
            "scroll_anchor": {
                "roles": ["dialog", "list"],
                "name_contains_any": ["people", "listeners", "participants"],
                "unique": True,
            },
        })
        cases.append(resign(scrolling_collection))

        browser_log = copy.deepcopy(base)
        browser_log["actions"].insert(3, {
            "op": "start_log_capture",
            "private_result": "space.browser-log",
            "max_entries": 50,
            "max_text_bytes": 4096,
        })
        browser_log["actions"].insert(-1, {"op": "stop_log_capture"})
        browser_log["result"]["private_fields"].append("space.browser-log")
        cases.append(resign(browser_log))

        requests = copy.deepcopy(base)
        requests["actions"].insert(3, {
            "op": "start_request_capture",
            "private_result": "space.requests",
            "max_entries": 50,
            "max_url_bytes": 4096,
        })
        requests["actions"].insert(-1, {"op": "stop_request_capture"})
        requests["result"]["private_fields"].append("space.requests")
        cases.append(resign(requests))

        console = copy.deepcopy(base)
        console["actions"].insert(3, {
            "op": "start_console_capture",
            "private_result": "space.console",
            "max_entries": 50,
            "max_arguments": 10,
            "max_argument_bytes": 4096,
        })
        console["actions"].insert(-1, {"op": "stop_console_capture"})
        console["result"]["private_fields"].append("space.console")
        cases.append(resign(console))

        unknown = copy.deepcopy(base)
        unknown["ambient_browsing"] = True
        cases.append(resign(unknown))

        unreviewed = copy.deepcopy(base)
        unreviewed["target"] = {
            "url": "https://example.invalid/synthetic",
            "origin": "https://example.invalid",
            "path_prefixes": ["/synthetic"],
            "collaboration_id": "e" * 64,
        }
        cases.append(resign(unreviewed))

        unsafe_regex = copy.deepcopy(base)
        unsafe_regex["actions"][3]["locator"]["name_matches"] = "(synthetic)+"
        cases.append(resign(unsafe_regex))

        boolean_scroll = copy.deepcopy(base)
        boolean_scroll["actions"].insert(2, {
            "op": "scroll_viewport", "direction": "down", "distance_px": True,
        })
        cases.append(resign(boolean_scroll))

        oversized_capture = copy.deepcopy(base)
        oversized_capture["actions"].insert(-1, {
            "op": "capture_viewport_private",
            "private_result": "space.viewport",
            "quality": 70,
            "max_bytes": 262145,
        })
        oversized_capture["result"]["private_fields"].append("space.viewport")
        cases.append(resign(oversized_capture))

        python_decisions = []
        for program in cases:
            try:
                validate_program(program)
                python_decisions.append(True)
            except ProtocolError:
                python_decisions.append(False)

        completed = subprocess.run(
            ["node", "tests/js/validate-programs.mjs"],
            cwd=ROOT,
            input=json.dumps(cases, separators=(",", ":")),
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        extension_decisions = json.loads(completed.stdout)
        self.assertEqual(extension_decisions, python_decisions)
        self.assertEqual(
            python_decisions,
            [True, True, True, True, True, True, True, False, True, False, False, False],
        )


if __name__ == "__main__":
    unittest.main()
