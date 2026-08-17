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

    def test_target_origin_path_and_fragment_are_exact(self) -> None:
        variants = []
        base = load_fixture("x-space-read-v1.json")
        wrong_origin = copy.deepcopy(base)
        wrong_origin["target"]["origin"] = "https://example.invalid"
        variants.append(wrong_origin)
        wrong_path = copy.deepcopy(base)
        wrong_path["target"]["path_prefixes"] = ["/unrelated/"]
        variants.append(wrong_path)
        fragment = copy.deepcopy(base)
        fragment["target"]["url"] += "#fragment"
        variants.append(fragment)
        for program in variants:
            resign(program)
            with self.assertRaises(ProtocolError):
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

        program = load_fixture("x-space-read-v1.json")
        program["result"]["private_fields"].append("space.unused")
        resign(program)
        with self.assertRaisesRegex(ProtocolError, "exactly match"):
            validate_program(program)

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
