from __future__ import annotations

import copy
import unittest
from typing import Any

from browser_executor.driver import DriverError, ProviderDriverSession
from browser_executor.protocol import BROWSER_PROTOCOL, canonical_program_sha256


class FakeDriverClient:
    def __init__(self) -> None:
        self.grant = {
            "collaboration_id": "a" * 64,
            "url": "https://example.invalid/synthetic",
            "origin": "https://example.invalid",
        }

    def collaborations(self) -> list[dict[str, str]]:
        return [dict(self.grant)]

    def run(self, program: dict[str, Any], **_kwargs: Any) -> dict[str, Any]:
        return {"status": "ok", "public": {"status": "ok"}, "private": {}}


def read_program() -> dict[str, Any]:
    value = {
        "protocol": BROWSER_PROTOCOL,
        "program_id": "provider-read-v1",
        "program_sha256": "0" * 64,
        "plan_sha256": "b" * 64,
        "driver": {"id": "synthetic-provider", "version": "1"},
        "capability": "read",
        "target": {
            "collaboration_id": "a" * 64,
            "url": "https://example.invalid/synthetic",
            "origin": "https://example.invalid",
            "path_prefixes": ["/synthetic"],
        },
        "limits": {"timeout_ms": 1000, "max_actions": 4, "max_repeat": 1},
        "private_slots": [],
        "actions": [
            {"op": "open_or_focus_exact_url"},
            {"op": "attach_debugger"},
            {"op": "detach_debugger"},
        ],
        "result": {"public_fields": ["status"], "private_fields": []},
    }
    value["program_sha256"] = canonical_program_sha256(value)
    return value


class ProviderDriverSessionTests(unittest.TestCase):
    def test_exact_plan_grant_and_postcondition_are_required(self) -> None:
        session = ProviderDriverSession("a" * 64, client=FakeDriverClient())
        result = session.execute(
            read_program(),
            approved_plan_sha256="b" * 64,
            verify=lambda _result: {"status": "verified"},
        )
        self.assertEqual(result.verification["status"], "verified")
        with self.assertRaisesRegex(DriverError, "approved plan"):
            session.execute(
                read_program(),
                approved_plan_sha256="c" * 64,
                verify=lambda _result: {"status": "verified"},
            )
        with self.assertRaisesRegex(DriverError, "postconditions"):
            session.execute(
                read_program(),
                approved_plan_sha256="b" * 64,
                verify=lambda _result: {"status": "unverified"},
            )

    def test_direct_agent_programs_are_not_provider_drivers(self) -> None:
        value = copy.deepcopy(read_program())
        value["driver"]["id"] = "agent-collaboration"
        value["program_sha256"] = canonical_program_sha256(value)
        session = ProviderDriverSession("a" * 64, client=FakeDriverClient())
        with self.assertRaisesRegex(DriverError, "own stable driver"):
            session.execute(
                value,
                approved_plan_sha256="b" * 64,
                verify=lambda _result: {"status": "verified"},
            )


if __name__ == "__main__":
    unittest.main()
