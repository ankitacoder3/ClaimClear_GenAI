"""Data shapes of the policy knowledge base."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(frozen=True)
class WordingInfo:
    """Where a policy wording came from. Recorded with every clause, so a citation names its exact source."""

    insurer: str
    product: str
    uin: str = ""                 # IRDAI unique identification number of the product
    version: str = ""             # e.g. the UIN suffix or the date printed on the wording
    source_url: str = ""
    downloaded_on: str = ""       # ISO date
    sha256: str = ""              # of the source file
    synthetic: bool = False       # True for test wordings: never cite these as policy wording

    @property
    def key(self) -> str:
        """Short identifier of this wording version, used in clause keys."""
        return self.uin or f"{self.insurer}|{self.product}|{self.version}"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Clause:
    """One numbered clause of the wording: the unit of retrieval and citation."""

    clause_id: str                # as printed, e.g. "5.2", "7.1", "Annexure I"
    title: str                    # e.g. "Items not reduced"
    text: str                     # the clause's own text, exactly as extracted
    section: str                  # top-level heading, e.g. "PROPORTIONATE DEDUCTION"
    parent_id: Optional[str]      # "5" for "5.2"; None for a top-level clause
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    codes: tuple[str, ...] = ()   # IRDAI exclusion codes in the clause, e.g. ("Excl01",)

    @property
    def heading(self) -> str:
        """Section and title, e.g. "PROPORTIONATE DEDUCTION > Items not reduced"."""
        parts = [p for p in (self.section, self.title) if p]
        return " > ".join(dict.fromkeys(parts))

    def index_text(self) -> str:
        """What is indexed: heading, clause number and text. Headings carry useful search terms."""
        return f"{self.clause_id} {self.heading}\n{self.text}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["codes"] = list(self.codes)
        return d


@dataclass
class SearchHit:
    """One search result."""

    clause_id: str
    title: str
    section: str
    text: str
    score: float                  # final score (reranker if used, else fused score)
    page_start: Optional[int]
    page_end: Optional[int]
    wording: str                  # WordingInfo.key
    synthetic: bool
    ranks: dict[str, Optional[int]] = field(default_factory=dict)   # rank in each retriever, 1-based

    def to_dict(self) -> dict:
        return asdict(self)
