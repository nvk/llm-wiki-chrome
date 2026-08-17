from __future__ import annotations

import hmac
from dataclasses import dataclass
from typing import Any, Callable

from .client import BrowserExecutorClient
from .protocol import SHA256, validate_program


class DriverError(RuntimeError):
    """Raised when a targeted adapter exceeds the provider-driver boundary."""


@dataclass(frozen=True)
class VerifiedProviderResult:
    execution: dict[str, Any]
    verification: dict[str, Any]


class ProviderDriverSession:
    """Bind one targeted adapter run to one exact click grant and verification callback.

    This helper does not plan, select elements, persist content, or weaken the typed
    protocol. It centralizes the exact target, approved-plan, mutation-boundary, and
    postcondition checks that every targeted provider adapter must perform.
    """

    def __init__(
        self, collaboration_id: str, *, client: BrowserExecutorClient | None = None
    ) -> None:
        self.client = client or BrowserExecutorClient()
        matches = [
            value
            for value in self.client.collaborations()
            if value.get("collaboration_id") == collaboration_id
        ]
        if len(matches) != 1:
            raise DriverError("the exact click grant is unavailable")
        self.collaboration = matches[0]

    def execute(
        self,
        program: dict[str, Any],
        *,
        approved_plan_sha256: str,
        private_values: dict[str, str] | None = None,
        authorize_mutation: Callable[[], None] | None = None,
        verify: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> VerifiedProviderResult:
        validated = validate_program(program)
        if not SHA256.fullmatch(approved_plan_sha256) or not hmac.compare_digest(
            validated["plan_sha256"],
            approved_plan_sha256,
        ):
            raise DriverError("the program is not bound to the approved plan")
        target = validated["target"]
        if (
            target["collaboration_id"] != self.collaboration["collaboration_id"]
            or target["url"] != self.collaboration["url"]
            or target["origin"] != self.collaboration["origin"]
        ):
            raise DriverError("the program target does not match the exact click grant")
        if validated["driver"]["id"] == "agent-collaboration":
            raise DriverError(
                "targeted adapters require their own stable driver identity"
            )
        if validated["capability"] == "mutation" and authorize_mutation is None:
            raise DriverError(
                "mutation execution requires the adapter authorization callback"
            )
        result = self.client.run(
            validated,
            private_values=private_values,
            before_mutation=authorize_mutation,
        )
        if result.get("status") != "ok":
            raise DriverError("the bounded browser program failed")
        verification = verify(result)
        if (
            not isinstance(verification, dict)
            or verification.get("status") != "verified"
        ):
            raise DriverError("the targeted adapter did not verify its postconditions")
        return VerifiedProviderResult(execution=result, verification=verification)
