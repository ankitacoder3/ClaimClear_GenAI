"""What the memory store keeps for each user.

Every record is written from a **tool result** (``get_policy``,
``audit_settlement_letter``, the approval gate, the insurer portal), never from
model text, and keeps the name of that ``source``. Money is held as ``Decimal``
rounded to paise and comes back as numbers in ``to_dict()``.

Records are keyed by the app's opaque ``user_id``. No names, phone numbers or
addresses are stored: the policy holder's name is dropped on purpose.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional

PAISE = Decimal("0.01")


def money(value) -> Optional[Decimal]:
    """A tool's amount (float, int, str or Decimal) as Decimal paise; ``None`` stays ``None``."""
    if value is None:
        return None
    return Decimal(str(value)).quantize(PAISE, rounding=ROUND_HALF_UP)


def _plain(d: dict) -> dict:
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in d.items()}


class GrievanceStatus:
    """Grievance lifecycle. Only the transitions in ``NEXT`` are allowed."""

    DRAFT = "draft"                    # text prepared, not yet approved
    APPROVED = "approved"              # the policyholder approved the exact text (approval gate, text_sha256)
    FILED = "filed"                    # sent to the insurer (portal reference number)
    ACKNOWLEDGED = "acknowledged"      # insurer confirmed receipt
    RESOLVED = "resolved"              # insurer agreed (fully or partly)
    REJECTED = "rejected"              # insurer refused
    ESCALATED = "escalated"            # taken to the ombudsman
    CLOSED = "closed"                  # nothing more will happen
    WITHDRAWN = "withdrawn"            # the policyholder dropped it

    NEXT: dict[str, frozenset[str]] = {
        DRAFT: frozenset({APPROVED, WITHDRAWN}),
        APPROVED: frozenset({FILED, WITHDRAWN}),
        FILED: frozenset({ACKNOWLEDGED, RESOLVED, REJECTED, WITHDRAWN}),
        ACKNOWLEDGED: frozenset({RESOLVED, REJECTED, WITHDRAWN}),
        RESOLVED: frozenset({CLOSED, ESCALATED}),
        REJECTED: frozenset({ESCALATED, CLOSED}),
        ESCALATED: frozenset({RESOLVED, REJECTED, CLOSED}),
        CLOSED: frozenset(),
        WITHDRAWN: frozenset(),
    }
    OPEN = frozenset({DRAFT, APPROVED, FILED, ACKNOWLEDGED, ESCALATED})
    ALL = frozenset(NEXT)


@dataclass(frozen=True)
class PolicyProfile:
    """The policy schedule the user verified a claim against (from ``get_policy``)."""

    policy_no: str
    insurer: str
    product: str
    sum_insured: Decimal
    period_start: str                 # ISO dates, as the servers return them
    period_end: str
    first_inception: str
    wording_uin: str = ""             # which policy wording policy-kb cites, if known
    source: str = "get_policy"
    updated_at: str = ""

    def to_dict(self) -> dict:
        return _plain(asdict(self))


@dataclass(frozen=True)
class ClaimRecord:
    """One verified claim: what the insurer paid and what ClaimClear found (from ``audit_settlement_letter``)."""

    claim_id: str
    policy_no: str
    admission: str
    discharge: str
    diagnosis: str
    procedure: str
    status: str                       # "settled" or "rejected": what claim history needs
    claimed_amount: Decimal
    insurer_paid: Decimal
    policy_payable: Optional[Decimal]
    disputable_amount: Optional[Decimal]
    unverified_amount: Optional[Decimal]
    verdicts: dict[str, int] = field(default_factory=dict)   # {"matches_policy": 3, "does_not_match_policy": 1}
    disputable_rows: tuple[str, ...] = ()                     # row IDs that may be disputed
    case_id: str = ""
    source: str = "audit_settlement_letter"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        d = _plain(asdict(self))
        d["disputable_rows"] = list(self.disputable_rows)
        return d

    def as_past_claim(self) -> dict:
        """In the settlement engine's ``PastClaimIn`` shape, so it can go into ``case["history"]``."""
        return {"claim_id": self.claim_id, "policy_no": self.policy_no, "admission": self.admission,
                "status": self.status, "settled_amount": float(self.insurer_paid),
                "diagnosis": self.diagnosis, "procedure": self.procedure}


@dataclass(frozen=True)
class LimitBalance:
    """A balance the engine reported for a policy period, e.g. sum insured or cataract limit left.

    Copied from the engine's ``*-REMAINING`` facts; it is the balance **before** the claim
    named in ``claim_id`` was paid. The engine, not memory, works balances out.
    """

    policy_no: str
    period_start: str
    fact_id: str                      # e.g. "F-SI-REMAINING", "F-CATARACT-REMAINING"
    rule_ref: str                     # e.g. "sum_insured", "cataract_limit"
    amount: Decimal
    text: str                         # the engine's own sentence
    claim_id: str
    recorded_at: str = ""

    def to_dict(self) -> dict:
        return _plain(asdict(self))


@dataclass(frozen=True)
class EpisodeRecord:
    """One earlier conversation, as topics only (``episodes.py``): the summary is scrubbed of amounts, numbers
    and contact details, so it can never be a source of figures. The vector is kept in the database, not here."""

    episode_id: str
    case_id: str
    claim_id: str
    summary: str
    topics: tuple[str, ...]
    turns: int                        # how many questions it covers (merged conversations add up)
    source: str                       # "chat" (extractive) or "chat:llm" (summarised by a model, then scrubbed)
    created_at: str
    updated_at: str
    recall_count: int = 0
    score: Optional[float] = None     # set by ``UserMemory.recall``

    def to_dict(self) -> dict:
        d = asdict(self)
        d["topics"] = list(self.topics)
        return d


@dataclass(frozen=True)
class GrievanceEvent:
    at: str
    status: str
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class GrievanceRecord:
    """A grievance about one claim. The text itself stays with the approval gate; memory keeps its hash."""

    grievance_id: str
    claim_id: str
    policy_no: str
    status: str
    row_ids: tuple[str, ...]
    disputable_amount: Optional[Decimal]      # copied from the claim's audit, never computed here
    text_sha256: str = ""
    reference_no: str = ""
    created_at: str = ""
    updated_at: str = ""
    events: tuple[GrievanceEvent, ...] = ()

    @property
    def is_open(self) -> bool:
        return self.status in GrievanceStatus.OPEN

    def to_dict(self) -> dict:
        d = _plain({k: v for k, v in asdict(self).items() if k != "events"})
        d["row_ids"] = list(self.row_ids)
        d["events"] = [e.to_dict() for e in self.events]
        d["is_open"] = self.is_open
        return d
