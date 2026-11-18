"""The memory store: SQLite (one file) or PostgreSQL, every row keyed by the app's ``user_id``.

    store = MemoryStore()                         # $CLAIMCLEAR_MEMORY_DB or <repo>/var/memory/memory.db
    store = MemoryStore("postgresql://user:pw@host:5432/db")      # production (see db.py)
    store.for_user("u_7f3a").grant_consent("app:settings")   # only from the user's own action in the app
    mem = store.session_memory("u_7f3a")          # UserMemory with consent, else NoMemory
    mem.remember_claim(case, letter_audit, case_id="case_...", letter=letter)
    mem.context()                                 # what to put in CaseState at the start of a session
    store.purge_expired()                         # daily retention job

Nothing is stored without consent to the current memory policy
(``POLICY_VERSION``, docs/memory_policy.md). There is no read that spans users:
the only way in is ``for_user``; the retention job is the only cross-user
operation, and it only deletes. Which session belongs to which user is the
app's job (Member 4).

Memory never computes money. Amounts are copied from tool results (the
settlement engine's audit), and claim history goes back to the engine, which
works out sub-limits and balances itself.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .db import Database, is_postgres
from . import episodes as ep
from .models import (
    ClaimRecord,
    EpisodeRecord,
    GrievanceEvent,
    GrievanceRecord,
    GrievanceStatus,
    LimitBalance,
    PolicyProfile,
    money,
)

DB_ENV = "CLAIMCLEAR_MEMORY_DB"
SCHEMA_VERSION = 3
POLICY_VERSION = "memory-policy-v2"    # the version of docs/memory_policy.md a user consents to
USER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
FINAL_STATUSES = ("computed", "not_admissible")
SHORT = 200
# Grievances that are finished or can only move on through the user starting something new.
EXPIRABLE_GRIEVANCES = (GrievanceStatus.CLOSED, GrievanceStatus.WITHDRAWN, GrievanceStatus.RESOLVED,
                        GrievanceStatus.REJECTED)


@dataclass(frozen=True)
class Retention:
    """How long memory keeps things (days). Stated to the user in docs/memory_policy.md."""

    claims_days: int = 730              # a claim, counted from when it was last verified
    closed_grievance_days: int = 365    # a closed, withdrawn, resolved or rejected grievance, from its last change
    inactive_days: int = 365            # everything, once the user hasn't used ClaimClear for this long
    episode_days: int = 180             # an earlier conversation (topics only), from when it was last updated

    def __post_init__(self):
        if min(self.claims_days, self.closed_grievance_days, self.inactive_days, self.episode_days) < 1:
            raise ValueError("retention periods must be at least one day")


@dataclass(frozen=True)
class ConsentStatus:
    """Whether memory may be used for this user."""

    active: bool                        # granted, for the current policy version
    policy_version: str = ""            # the version the user agreed to ("" if never)
    granted_at: str = ""
    source: str = ""                    # where it was given, e.g. "app:settings"
    needs_renewal: bool = False         # agreed to an older policy version

    def to_dict(self) -> dict:
        return asdict(self)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS policies (
    user_id TEXT NOT NULL, policy_no TEXT NOT NULL,
    insurer TEXT NOT NULL, product TEXT NOT NULL, sum_insured TEXT NOT NULL,
    period_start TEXT NOT NULL, period_end TEXT NOT NULL, first_inception TEXT NOT NULL,
    wording_uin TEXT NOT NULL, source TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, policy_no));
CREATE TABLE IF NOT EXISTS claims (
    user_id TEXT NOT NULL, claim_id TEXT NOT NULL, policy_no TEXT NOT NULL,
    admission TEXT NOT NULL, discharge TEXT NOT NULL, diagnosis TEXT NOT NULL, procedure TEXT NOT NULL,
    status TEXT NOT NULL, claimed_amount TEXT NOT NULL, insurer_paid TEXT NOT NULL,
    policy_payable TEXT, disputable_amount TEXT, unverified_amount TEXT,
    verdicts TEXT NOT NULL, disputable_rows TEXT NOT NULL, case_id TEXT NOT NULL, source TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, claim_id));
CREATE TABLE IF NOT EXISTS balances (
    user_id TEXT NOT NULL, policy_no TEXT NOT NULL, period_start TEXT NOT NULL, fact_id TEXT NOT NULL,
    rule_ref TEXT NOT NULL, amount TEXT NOT NULL, text TEXT NOT NULL,
    claim_id TEXT NOT NULL, claim_admission TEXT NOT NULL, recorded_at TEXT NOT NULL,
    PRIMARY KEY (user_id, policy_no, period_start, fact_id));
CREATE TABLE IF NOT EXISTS grievances (
    user_id TEXT NOT NULL, grievance_id TEXT NOT NULL, claim_id TEXT NOT NULL, policy_no TEXT NOT NULL,
    status TEXT NOT NULL, row_ids TEXT NOT NULL, disputable_amount TEXT,
    text_sha256 TEXT NOT NULL, reference_no TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    PRIMARY KEY (user_id, grievance_id));
CREATE TABLE IF NOT EXISTS grievance_events (
    user_id TEXT NOT NULL, grievance_id TEXT NOT NULL, seq INTEGER NOT NULL,
    at TEXT NOT NULL, status TEXT NOT NULL, note TEXT NOT NULL,
    PRIMARY KEY (user_id, grievance_id, seq));
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY, consent_version TEXT NOT NULL, consent_at TEXT NOT NULL,
    consent_source TEXT NOT NULL, last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS consent_events (
    user_id TEXT NOT NULL, seq INTEGER NOT NULL, at TEXT NOT NULL, action TEXT NOT NULL,
    policy_version TEXT NOT NULL, source TEXT NOT NULL,
    PRIMARY KEY (user_id, seq));
CREATE TABLE IF NOT EXISTS episodes (
    user_id TEXT NOT NULL, episode_id TEXT NOT NULL, case_id TEXT NOT NULL, claim_id TEXT NOT NULL,
    summary TEXT NOT NULL, topics TEXT NOT NULL, turns INTEGER NOT NULL, source TEXT NOT NULL,
    embedder TEXT NOT NULL, vector TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    recalled_at TEXT NOT NULL, recall_count INTEGER NOT NULL,
    PRIMARY KEY (user_id, episode_id));
"""

USER_TABLES = ("policies", "claims", "balances", "grievances", "grievance_events", "episodes", "users",
               "consent_events")


def _columns(table: str) -> list[str]:
    """Column names of a table, read from ``_SCHEMA`` (so the upserts can't drift from it)."""
    body = re.search(rf"CREATE TABLE IF NOT EXISTS {table} \((.*?)\);", _SCHEMA, re.S).group(1)
    body = re.sub(r",?\s*PRIMARY KEY \([^)]*\)", "", body)
    return [part.split()[0] for part in body.split(",") if part.strip()]


def _upsert(table: str, key: tuple[str, ...]) -> str:
    """``INSERT ... ON CONFLICT (key) DO UPDATE``: portable across SQLite (3.24+) and PostgreSQL."""
    cols = _columns(table)
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c not in key)
    return (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT ({', '.join(key)}) DO UPDATE SET {updates}")


class MemoryStoreError(Exception):
    """A refused read or write, with a code the caller can act on."""

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def default_db_path() -> Path | str:
    """``$CLAIMCLEAR_MEMORY_DB`` (a file path or a postgresql:// URL), else ``<repo>/var/memory/memory.db``."""
    env = os.environ.get(DB_ENV)
    if env:
        return env if is_postgres(env) else Path(env)
    return Path(__file__).resolve().parents[2] / "var" / "memory" / "memory.db"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require(data: dict, keys: Iterable[str], what: str) -> None:
    missing = [k for k in keys if data.get(k) in (None, "")]
    if missing:
        raise MemoryStoreError("MISSING_FIELD", f"{what} is missing {', '.join(missing)}")


def _text(value: Any, limit: int = SHORT) -> str:
    return str(value or "")[:limit]


def _dec(value: Optional[str]) -> Optional[Decimal]:
    return None if value is None else Decimal(value)


def _s(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else str(value)


class MemoryStore:
    """Opens (and creates) the database. Cheap to construct; each operation uses its own connection."""

    def __init__(self, path: Optional[str | Path] = None, clock: Callable[[], datetime] = _utc_now,
                 retention: Retention = Retention()):
        target = path or default_db_path()
        self.db = Database(target)
        self.path = None if self.db.postgres else self.db.target     # the SQLite file (None on PostgreSQL)
        self._clock = clock
        self.retention = retention
        with self.connect() as con:
            row = None
            if self.db.has_table(con, "meta"):
                row = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if row is not None and int(row[0]) > SCHEMA_VERSION:
                raise MemoryStoreError("SCHEMA_VERSION", f"database schema {row[0]}, code expects {SCHEMA_VERSION}")
            con.executescript(_SCHEMA)              # v1 -> v2 -> v3 only add tables (users, consent_events; episodes)
            if row is not None and int(row[0]) == 1:
                # v1 had no consent: existing rows can't be used until the user consents, so mark them
                # with an empty consent version (inactive) and today's date as last seen.
                now = self.now()
                for (uid,) in con.execute("SELECT DISTINCT user_id FROM policies UNION "
                                          "SELECT DISTINCT user_id FROM claims").fetchall():
                    con.execute("INSERT INTO users VALUES (?, '', '', 'migrated-v1', ?) "
                                "ON CONFLICT (user_id) DO NOTHING", (uid, now))
            con.execute("INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
                        "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(SCHEMA_VERSION),))

    def connect(self):
        """A connection (SQLite or PostgreSQL) that commits on success and rolls back on error."""
        return self.db.connect()

    def now(self) -> str:
        return self._clock().astimezone(timezone.utc).isoformat(timespec="seconds")

    def for_user(self, user_id: str) -> "UserMemory":
        """Everything for one user. ``user_id`` is the app's opaque ID, never a name or phone number."""
        if not isinstance(user_id, str) or not USER_ID.match(user_id):
            raise MemoryStoreError("INVALID_USER", "user_id must be 1-128 characters: letters, digits, _ . : -")
        return UserMemory(self, user_id)

    def session_memory(self, user_id: str, memory_on: bool = True) -> "UserMemory | NoMemory":
        """What a session should use: the user's memory if it is switched on and the user has consented to
        the current policy, else ``NoMemory`` (same interface, stores nothing)."""
        mem = self.for_user(user_id)
        return mem if memory_on and mem.consent().active else NoMemory(user_id)

    def cutoff(self, days: int) -> str:
        return (self._clock().astimezone(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")

    def purge_expired(self) -> dict[str, int]:
        """Apply the retention rules to every user (a daily job for the app). Returns rows deleted per table."""
        with self.connect() as con:
            users = {r[0] for t in ("users", "policies", "claims", "grievances")
                     for r in con.execute(f"SELECT DISTINCT user_id FROM {t}").fetchall()}
        total: dict[str, int] = {t: 0 for t in USER_TABLES}
        for uid in sorted(users):
            for table, n in UserMemory(self, uid).purge_expired().items():
                total[table] += n
        return total


class UserMemory:
    """One user's memory. Get it from ``MemoryStore.for_user``."""

    enabled = True

    def __init__(self, store: MemoryStore, user_id: str):
        self._store = store
        self.user_id = user_id

    # ------------------------------------------------------------------ consent

    def consent(self) -> ConsentStatus:
        """Whether this user has agreed to the current memory policy (``POLICY_VERSION``)."""
        rows = self._rows("SELECT * FROM users WHERE user_id=?")
        if not rows or not rows[0]["consent_version"]:
            return ConsentStatus(False)
        r = rows[0]
        current = r["consent_version"] == POLICY_VERSION
        return ConsentStatus(current, r["consent_version"], r["consent_at"], r["consent_source"],
                             needs_renewal=not current)

    def grant_consent(self, source: str, policy_version: str = POLICY_VERSION) -> ConsentStatus:
        """Record that the user agreed to the memory policy. Call it only from the user's own action in the
        app (``source`` says where, e.g. ``"app:settings"``), never from an agent."""
        if policy_version != POLICY_VERSION:
            raise MemoryStoreError("POLICY_VERSION", f"consent must be to the current policy {POLICY_VERSION!r}")
        if not source:
            raise MemoryStoreError("MISSING_FIELD", "say where the consent was given (source)")
        now = self._store.now()
        with self._store.connect() as con:
            con.execute("INSERT INTO users VALUES (?,?,?,?,?) ON CONFLICT (user_id) DO UPDATE SET "
                        "consent_version=excluded.consent_version, consent_at=excluded.consent_at, "
                        "consent_source=excluded.consent_source, last_seen=excluded.last_seen",
                        (self.user_id, policy_version, now, _text(source, 64), now))
            self._consent_event(con, "granted", policy_version, source, now)
        return self.consent()

    def withdraw_consent(self, source: str, delete_data: bool = True) -> dict[str, int]:
        """The user switched memory off. By default everything stored is deleted too (as ``forget``);
        with ``delete_data=False`` the data stays (for ``export``) but is never used or added to."""
        if delete_data:
            return self.forget()
        now = self._store.now()
        with self._store.connect() as con:
            con.execute("UPDATE users SET consent_version='', consent_at='', consent_source=?, last_seen=? "
                        "WHERE user_id=?", (_text(source, 64), now, self.user_id))
            self._consent_event(con, "withdrawn", "", source, now)
        return {t: 0 for t in USER_TABLES}

    def consent_log(self) -> list[dict]:
        return [dict(r) for r in self._rows("SELECT at, action, policy_version, source FROM consent_events "
                                            "WHERE user_id=? ORDER BY seq")]

    def _consent_event(self, con: Any, action: str, version: str, source: str, at: str) -> None:
        seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM consent_events WHERE user_id=?",
                          (self.user_id,)).fetchone()[0]
        con.execute("INSERT INTO consent_events VALUES (?,?,?,?,?,?)",
                    (self.user_id, seq, at, action, version, _text(source, 64)))

    def _check_consent(self) -> None:
        status = self.consent()
        if not status.active:
            why = (f"the user agreed to {status.policy_version!r}, not the current {POLICY_VERSION!r}"
                   if status.needs_renewal else "the user has not agreed to memory")
            raise MemoryStoreError("NO_CONSENT", f"{why}; nothing is stored (use session_memory to get NoMemory)")

    def _touch(self, con: Any) -> None:
        con.execute("UPDATE users SET last_seen=? WHERE user_id=?", (self._store.now(), self.user_id))

    # ------------------------------------------------------------------ expiry

    def purge_expired(self) -> dict[str, int]:
        """Delete what the retention rules say is too old (``MemoryStore.retention``). Returns rows deleted
        per table. ``context()`` runs it first, so expired data never reaches an agent."""
        r = self._store.retention
        counts = {t: 0 for t in USER_TABLES}
        rows = self._rows("SELECT last_seen FROM users WHERE user_id=?")
        if rows and rows[0]["last_seen"] < self._store.cutoff(r.inactive_days):
            return self.forget()                                      # inactive for too long: everything goes
        claims_cut = self._store.cutoff(r.claims_days)
        grievance_cut = self._store.cutoff(r.closed_grievance_days)
        uid = self.user_id
        with self._store.connect() as con:
            counts["episodes"] = con.execute("DELETE FROM episodes WHERE user_id=? AND updated_at < ?",
                                             (uid, self._store.cutoff(r.episode_days))).rowcount
            done = ",".join("?" * len(EXPIRABLE_GRIEVANCES))
            old = [g[0] for g in con.execute(
                f"SELECT grievance_id FROM grievances WHERE user_id=? AND status IN ({done}) AND updated_at < ?",
                (uid, *EXPIRABLE_GRIEVANCES, grievance_cut)).fetchall()]
            for gid in old:
                counts["grievance_events"] += con.execute(
                    "DELETE FROM grievance_events WHERE user_id=? AND grievance_id=?", (uid, gid)).rowcount
                counts["grievances"] += con.execute(
                    "DELETE FROM grievances WHERE user_id=? AND grievance_id=?", (uid, gid)).rowcount
            # a claim stays while any grievance about it is still stored
            counts["claims"] = con.execute(
                "DELETE FROM claims WHERE user_id=? AND updated_at < ? AND claim_id NOT IN "
                "(SELECT claim_id FROM grievances WHERE user_id=?)", (uid, claims_cut, uid)).rowcount
            # balances of a policy period that is no longer the current one, or of a forgotten policy
            counts["balances"] = con.execute(
                "DELETE FROM balances WHERE user_id=? AND NOT EXISTS (SELECT 1 FROM policies p WHERE "
                "p.user_id=balances.user_id AND p.policy_no=balances.policy_no AND "
                "p.period_start=balances.period_start)", (uid,)).rowcount
            counts["policies"] = con.execute(
                "DELETE FROM policies WHERE user_id=? AND updated_at < ? AND policy_no NOT IN "
                "(SELECT policy_no FROM claims WHERE user_id=?)", (uid, claims_cut, uid)).rowcount
            if counts["policies"]:
                counts["balances"] += con.execute(
                    "DELETE FROM balances WHERE user_id=? AND policy_no NOT IN "
                    "(SELECT policy_no FROM policies WHERE user_id=?)", (uid, uid)).rowcount
        return counts

    # ------------------------------------------------------------------ writes (from tool results only)

    def remember_policy(self, policy: dict, wording_uin: str = "", source: str = "get_policy") -> PolicyProfile:
        """Store or update the policy schedule (a ``get_policy`` result). The holder's name is not kept."""
        self._check_consent()
        _require(policy, ("policy_no", "sum_insured", "period_start", "period_end", "first_inception"), "policy")
        now = self._store.now()
        p = PolicyProfile(policy_no=_text(policy["policy_no"], 64), insurer=_text(policy.get("insurer")),
                          product=_text(policy.get("product")), sum_insured=money(policy["sum_insured"]),
                          period_start=str(policy["period_start"]), period_end=str(policy["period_end"]),
                          first_inception=str(policy["first_inception"]), wording_uin=_text(wording_uin, 64),
                          source=_text(source, 64), updated_at=now)
        with self._store.connect() as con:
            old = con.execute("SELECT wording_uin FROM policies WHERE user_id = ? AND policy_no = ?",
                              (self.user_id, p.policy_no)).fetchone()
            uin = p.wording_uin or (old["wording_uin"] if old else "")
            con.execute(
                "INSERT INTO policies VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (user_id, policy_no) DO UPDATE SET "
                "insurer=excluded.insurer, product=excluded.product, sum_insured=excluded.sum_insured, "
                "period_start=excluded.period_start, period_end=excluded.period_end, "
                "first_inception=excluded.first_inception, wording_uin=excluded.wording_uin, "
                "source=excluded.source, updated_at=excluded.updated_at",
                (self.user_id, p.policy_no, p.insurer, p.product, str(p.sum_insured), p.period_start,
                 p.period_end, p.first_inception, uin, p.source, now))
            self._touch(con)
        return self.profile(p.policy_no)  # type: ignore[return-value]

    def remember_claim(self, case: dict, letter_audit: dict, case_id: str = "",
                       letter: Optional[dict] = None) -> ClaimRecord:
        """Store a verified claim from the ``case`` sent to the engine and the ``audit_settlement_letter`` result.

        Also stores the policy and the engine's balance facts (``*-REMAINING``). Refuses an audit
        that is still waiting for the policyholder's answers.
        """
        self._check_consent()
        _require(case, ("claim", "policy"), "case")
        claim, policy = case["claim"], case["policy"]
        _require(claim, ("claim_id", "policy_no", "admission", "discharge"), "claim")
        settlement = letter_audit.get("settlement") or {}
        if settlement.get("claim_id") != claim["claim_id"]:
            raise MemoryStoreError("CLAIM_MISMATCH", "the audit is for another claim than the case")
        if claim["policy_no"] != policy.get("policy_no"):
            raise MemoryStoreError("CLAIM_MISMATCH", "the claim and the policy have different policy numbers")
        if settlement.get("status") not in FINAL_STATUSES:
            raise MemoryStoreError("NOT_FINAL", f"settlement status is {settlement.get('status')!r}; "
                                                "answer the engine's questions and audit again before remembering")
        self.remember_policy(policy)

        rows = letter_audit.get("rows") or []
        verdicts: dict[str, int] = {}
        for r in rows:
            verdicts[r["verdict"]] = verdicts.get(r["verdict"], 0) + 1
        disputable_rows = tuple(r["row_id"] for r in rows
                                if r["verdict"] == "does_not_match_policy" and (r.get("difference") or 0) > 0)
        paid = money(letter_audit.get("insurer_paid", 0))
        rejected = (letter or {}).get("letter_type") == "rejection" or paid == 0
        now = self._store.now()
        with self._store.connect() as con:
            old = con.execute("SELECT created_at FROM claims WHERE user_id = ? AND claim_id = ?",
                              (self.user_id, claim["claim_id"])).fetchone()
            con.execute(
                _upsert("claims", ("user_id", "claim_id")),
                (self.user_id, _text(claim["claim_id"], 64), claim["policy_no"], str(claim["admission"]),
                 str(claim["discharge"]), _text(claim.get("diagnosis")), _text(claim.get("procedure")),
                 "rejected" if rejected else "settled", str(money(settlement.get("claimed_amount", 0))), str(paid),
                 _s(money(letter_audit.get("policy_payable"))), _s(money(letter_audit.get("disputable_amount"))),
                 _s(money(letter_audit.get("unverified_amount"))), json.dumps(verdicts, sort_keys=True),
                 json.dumps(list(disputable_rows)), _text(case_id, 64), "audit_settlement_letter",
                 old["created_at"] if old else now, now))
            self._touch(con)
            for f in settlement.get("facts") or []:
                if f.get("kind") != "limit" or not str(f.get("fact_id", "")).endswith("-REMAINING") \
                        or f.get("amount") is None:
                    continue
                current = con.execute(
                    "SELECT claim_admission FROM balances WHERE user_id=? AND policy_no=? AND period_start=? "
                    "AND fact_id=?", (self.user_id, policy["policy_no"], str(policy["period_start"]),
                                      f["fact_id"])).fetchone()
                if current and current["claim_admission"] > str(claim["admission"]):
                    continue                     # keep the balance from the later claim
                con.execute(_upsert("balances", ("user_id", "policy_no", "period_start", "fact_id")),
                            (self.user_id, policy["policy_no"], str(policy["period_start"]), f["fact_id"],
                             _text(f.get("rule_ref"), 64), str(money(f["amount"])), _text(f.get("text"), 500),
                             claim["claim_id"], str(claim["admission"]), now))
        return self.claim(claim["claim_id"])  # type: ignore[return-value]

    def open_grievance(self, claim_id: str, row_ids: Optional[Iterable[str]] = None, note: str = "") -> GrievanceRecord:
        """Start a grievance (status ``draft``) about rows the audit found disputable.

        ``row_ids`` default to every disputable row; a row the audit did not find disputable is
        refused, which protects against false disputes. The amount is copied from the audit.
        """
        self._check_consent()
        claim = self.claim(claim_id)
        if claim is None:
            raise MemoryStoreError("CLAIM_NOT_FOUND", f"no remembered claim {claim_id!r}")
        if not claim.disputable_amount or claim.disputable_amount <= 0 or not claim.disputable_rows:
            raise MemoryStoreError("NOTHING_TO_DISPUTE", "the audit found nothing that may be disputed")
        rows = tuple(row_ids) if row_ids is not None else claim.disputable_rows
        bad = [r for r in rows if r not in claim.disputable_rows]
        if bad or not rows:
            raise MemoryStoreError("ROW_NOT_DISPUTABLE", f"not disputable per the audit: {', '.join(bad) or 'none'}; "
                                                         f"disputable rows: {', '.join(claim.disputable_rows)}")
        gid = f"grv_{uuid.uuid4().hex[:12]}"
        now = self._store.now()
        with self._store.connect() as con:
            con.execute("INSERT INTO grievances VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (self.user_id, gid, claim.claim_id, claim.policy_no, GrievanceStatus.DRAFT,
                         json.dumps(list(rows)), _s(claim.disputable_amount), "", "", now, now))
            self._event(con, gid, GrievanceStatus.DRAFT, note, now)
        return self.grievance(gid)  # type: ignore[return-value]

    def update_grievance(self, grievance_id: str, status: str, *, text_sha256: Optional[str] = None,
                         reference_no: Optional[str] = None, note: str = "") -> GrievanceRecord:
        """Move a grievance to ``status``. ``approved`` needs the approval gate's ``text_sha256``;
        ``filed`` needs the portal's ``reference_no``."""
        self._check_consent()
        g = self.grievance(grievance_id)
        if g is None:
            raise MemoryStoreError("GRIEVANCE_NOT_FOUND", f"no grievance {grievance_id!r}")
        if status not in GrievanceStatus.NEXT.get(g.status, frozenset()):
            allowed = ", ".join(sorted(GrievanceStatus.NEXT.get(g.status, ()))) or "none"
            raise MemoryStoreError("BAD_TRANSITION", f"{g.status} -> {status} is not allowed (allowed: {allowed})")
        sha = g.text_sha256
        ref = g.reference_no
        if status == GrievanceStatus.APPROVED:
            if not text_sha256 or not SHA256.match(text_sha256):
                raise MemoryStoreError("INVALID_HASH", "approval needs the SHA-256 (64 lowercase hex) of the exact text")
            sha = text_sha256
        if status == GrievanceStatus.FILED:
            if not reference_no:
                raise MemoryStoreError("MISSING_FIELD", "filing needs the portal's reference_no")
            ref = _text(reference_no, 64)
        now = self._store.now()
        with self._store.connect() as con:
            con.execute("UPDATE grievances SET status=?, text_sha256=?, reference_no=?, updated_at=? "
                        "WHERE user_id=? AND grievance_id=?", (status, sha, ref, now, self.user_id, grievance_id))
            self._event(con, grievance_id, status, note, now)
        return self.grievance(grievance_id)  # type: ignore[return-value]

    def _event(self, con: Any, gid: str, status: str, note: str, at: str) -> None:
        seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM grievance_events WHERE user_id=? AND grievance_id=?",
                          (self.user_id, gid)).fetchone()[0]
        con.execute("INSERT INTO grievance_events VALUES (?,?,?,?,?,?)",
                    (self.user_id, gid, seq, at, status, _text(note, 500)))
        self._touch(con)

    # ------------------------------------------------------------------ reads

    def _rows(self, sql: str, args: tuple = ()) -> list:
        with self._store.connect() as con:
            return con.execute(sql, (self.user_id, *args)).fetchall()

    def profiles(self) -> list[PolicyProfile]:
        return [_profile(r) for r in self._rows("SELECT * FROM policies WHERE user_id=? ORDER BY period_start DESC")]

    def profile(self, policy_no: str) -> Optional[PolicyProfile]:
        rows = self._rows("SELECT * FROM policies WHERE user_id=? AND policy_no=?", (policy_no,))
        return _profile(rows[0]) if rows else None

    def claims(self, policy_no: Optional[str] = None, limit: Optional[int] = None) -> list[ClaimRecord]:
        """Newest admission first."""
        sql, args = "SELECT * FROM claims WHERE user_id=?", ()
        if policy_no:
            sql, args = sql + " AND policy_no=?", (policy_no,)
        sql += " ORDER BY admission DESC, claim_id"
        if limit:
            sql, args = sql + " LIMIT ?", (*args, int(limit))
        return [_claim(r) for r in self._rows(sql, args)]

    def claim(self, claim_id: str) -> Optional[ClaimRecord]:
        rows = self._rows("SELECT * FROM claims WHERE user_id=? AND claim_id=?", (claim_id,))
        return _claim(rows[0]) if rows else None

    def claim_history(self, policy_no: str) -> list[dict]:
        """Remembered claims on ``policy_no`` in the engine's ``PastClaimIn`` shape (every year; the engine
        keeps only the current period). Combine with ``get_claim_history`` using ``merge_history``."""
        return [c.as_past_claim() for c in reversed(self.claims(policy_no))]

    def balances(self, policy_no: Optional[str] = None) -> list[LimitBalance]:
        """The engine's latest balances for each policy's current period (from the stored profile)."""
        out = []
        for p in self.profiles():
            if policy_no and p.policy_no != policy_no:
                continue
            out += [_balance(r) for r in self._rows(
                "SELECT * FROM balances WHERE user_id=? AND policy_no=? AND period_start=? ORDER BY fact_id",
                (p.policy_no, p.period_start))]
        return out

    def grievances(self, open_only: bool = False) -> list[GrievanceRecord]:
        rows = self._rows("SELECT grievance_id FROM grievances WHERE user_id=? ORDER BY created_at DESC, grievance_id")
        out = [self.grievance(r["grievance_id"]) for r in rows]
        return [g for g in out if g is not None and (g.is_open or not open_only)]

    def grievance(self, grievance_id: str) -> Optional[GrievanceRecord]:
        rows = self._rows("SELECT * FROM grievances WHERE user_id=? AND grievance_id=?", (grievance_id,))
        if not rows:
            return None
        events = self._rows("SELECT * FROM grievance_events WHERE user_id=? AND grievance_id=? ORDER BY seq",
                            (grievance_id,))
        return _grievance(rows[0], [GrievanceEvent(e["at"], e["status"], e["note"]) for e in events])

    # ------------------------------------------------------------------ for the agents

    def context(self, max_claims: int = 5, policy_no: Optional[str] = None) -> dict:
        """What the agents may know about this user at the start of a session (see ``context.py``).

        Expired data is purged first. Without current consent the context is empty (``enabled`` false).
        Counts as activity for the inactivity rule.
        """
        from .context import build_context
        if not self.consent().active:
            return build_context(NoMemory(self.user_id), max_claims, policy_no)
        self.purge_expired()
        if not self.consent().active:                   # purge removed an inactive user
            return build_context(NoMemory(self.user_id), max_claims, policy_no)
        with self._store.connect() as con:
            self._touch(con)
        return build_context(self, max_claims, policy_no)

    # ------------------------------------------------------------------ episodic memory (conversations, topics only)

    def remember_conversation(self, turns: Iterable[tuple[str, str]], *, case_id: str = "", claim_id: str = "",
                              summary: Optional[str] = None, source: str = "chat",
                              embedder: Optional[ep.Embedder] = None) -> Optional[EpisodeRecord]:
        """Remember what a finished conversation was about (``episodes.py``).

        ``turns`` are ``(question, answer)`` pairs; only the questions are used when no ``summary`` is given.
        A ``summary`` written by a model is accepted but always scrubbed: amounts, numbers, contacts and long
        identifiers are removed (``UnsafeSummary`` if an amount survives). A near-duplicate of an earlier
        conversation about the same case is merged into it. Returns ``None`` when there is nothing to keep.
        """
        self._check_consent()
        turns = [(str(q or ""), str(a or "")) for q, a in turns]
        questions = [q for q, _ in turns if q.strip()]
        if not questions:
            return None
        raw = summary if summary and summary.strip() else ep.extractive_summary(turns)
        text = ep.scrub(raw)
        if not text:
            return None
        topics = ep.topics_of(" ".join(questions) + " " + text)
        emb = embedder or ep.HashingEmbedder()
        vector = emb.embed([text + " " + " ".join(topics)])[0]
        now = self._store.now()
        case_id, claim_id = _text(case_id, 64), _text(claim_id, 64)
        with self._store.connect() as con:
            same = con.execute("SELECT * FROM episodes WHERE user_id=? AND case_id=? AND embedder=?",
                               (self.user_id, case_id, emb.name)).fetchall()
            best = max(same, key=lambda r: ep.cosine(vector, json.loads(r["vector"])), default=None)
            if best is not None and ep.cosine(vector, json.loads(best["vector"])) >= ep.MERGE_SIMILARITY:
                gid = best["episode_id"]
                merged = list(dict.fromkeys(json.loads(best["topics"]) + topics))
                con.execute("UPDATE episodes SET summary=?, topics=?, turns=?, source=?, vector=?, claim_id=?, "
                            "updated_at=? WHERE user_id=? AND episode_id=?",
                            (text, json.dumps(merged), int(best["turns"]) + len(questions), _text(source, 32),
                             json.dumps(vector), claim_id or best["claim_id"], now, self.user_id, gid))
            else:
                gid = f"eps_{uuid.uuid4().hex[:12]}"
                con.execute(_upsert("episodes", ("user_id", "episode_id")),
                            (self.user_id, gid, case_id, claim_id, text, json.dumps(topics), len(questions),
                             _text(source, 32), emb.name, json.dumps(vector), now, now, "", 0))
            # keep at most MAX_EPISODES: the least recalled, then the oldest, go first
            total = con.execute("SELECT COUNT(*) FROM episodes WHERE user_id=?", (self.user_id,)).fetchone()[0]
            extra = total - ep.MAX_EPISODES
            if extra > 0:
                old = con.execute("SELECT episode_id FROM episodes WHERE user_id=? AND episode_id<>? "
                                  "ORDER BY recall_count, updated_at LIMIT ?", (self.user_id, gid, extra)).fetchall()
                for (oid,) in old:
                    con.execute("DELETE FROM episodes WHERE user_id=? AND episode_id=?", (self.user_id, oid))
            self._touch(con)
        return self.episode(gid)

    def recall(self, query: str, k: int = ep.DEFAULT_K, embedder: Optional[ep.Embedder] = None,
               case_id: Optional[str] = None) -> list[EpisodeRecord]:
        """Earlier conversations relevant to ``query``: hybrid (vectors + BM25, fused with RRF) and weighted by
        recency. Empty without consent. Expired episodes are purged first; recalled ones are marked as used."""
        if not (query or "").strip() or not self.consent().active:
            return []
        self.purge_expired()
        if not self.consent().active:
            return []
        emb = embedder or ep.HashingEmbedder()
        sql, args = "SELECT * FROM episodes WHERE user_id=?", ()
        if case_id is not None:
            sql, args = sql + " AND case_id=?", (case_id,)
        items = []
        for r in self._rows(sql, args):
            topics = json.loads(r["topics"])
            vec = json.loads(r["vector"]) if r["embedder"] == emb.name else \
                emb.embed([r["summary"] + " " + " ".join(topics)])[0]          # another embedder: re-embed
            items.append({"row": r, "summary": r["summary"], "topics": topics, "vector": vec,
                          "updated_at": r["updated_at"]})
        found = ep.rank(query, items, emb.embed([query])[0], self._store._clock().astimezone(timezone.utc), k)
        if not found:
            return []
        now = self._store.now()
        with self._store.connect() as con:
            for _, it in found:
                con.execute("UPDATE episodes SET recalled_at=?, recall_count=recall_count+1 WHERE user_id=? AND "
                            "episode_id=?", (now, self.user_id, it["row"]["episode_id"]))
            self._touch(con)
        return [_episode(it["row"], score) for score, it in found]

    def episodes(self, limit: Optional[int] = None) -> list[EpisodeRecord]:
        """Every remembered conversation, newest first."""
        sql, args = "SELECT * FROM episodes WHERE user_id=? ORDER BY updated_at DESC, episode_id", ()
        if limit:
            sql, args = sql + " LIMIT ?", (int(limit),)
        return [_episode(r) for r in self._rows(sql, args)]

    def episode(self, episode_id: str) -> Optional[EpisodeRecord]:
        rows = self._rows("SELECT * FROM episodes WHERE user_id=? AND episode_id=?", (episode_id,))
        return _episode(rows[0]) if rows else None

    # ------------------------------------------------------------------ the user's own data

    def export(self) -> dict:
        """Everything stored for this user, for "what do you remember about me?". Works without consent."""
        return {"user_id": self.user_id, "exported_at": self._store.now(), "consent": self.consent().to_dict(),
                "consent_log": self.consent_log(),
                "policies": [p.to_dict() for p in self.profiles()],
                "claims": [c.to_dict() for c in self.claims()],
                "balances": [b.to_dict() for b in self.balances()],
                "grievances": [g.to_dict() for g in self.grievances()],
                "episodes": [e.to_dict() for e in self.episodes()]}

    def forget(self) -> dict[str, int]:
        """Delete everything stored for this user ("forget my data"), consent record included, so memory
        stays off until the user agrees again. Returns the rows deleted per table."""
        counts = {}
        with self._store.connect() as con:
            for table in USER_TABLES:
                counts[table] = con.execute(f"DELETE FROM {table} WHERE user_id = ?", (self.user_id,)).rowcount
        return counts


class NoMemory:
    """The same interface, storing nothing: memory switched off (the "memory off" runs, or no consent)."""

    enabled = False

    def __init__(self, user_id: str = "anonymous"):
        self.user_id = user_id

    def consent(self) -> ConsentStatus:
        return ConsentStatus(False)

    def consent_log(self) -> list:
        return []

    def withdraw_consent(self, source: str, delete_data: bool = True) -> dict[str, int]:
        return {t: 0 for t in USER_TABLES}

    def purge_expired(self) -> dict[str, int]:
        return {t: 0 for t in USER_TABLES}

    def remember_policy(self, policy: dict, wording_uin: str = "", source: str = "get_policy") -> None:
        return None

    def remember_claim(self, case: dict, letter_audit: dict, case_id: str = "", letter: Optional[dict] = None) -> None:
        return None

    def open_grievance(self, claim_id: str, row_ids: Optional[Iterable[str]] = None, note: str = "") -> None:
        return None

    def remember_conversation(self, turns, **kwargs) -> None:
        return None

    def recall(self, query: str, k: int = ep.DEFAULT_K, embedder=None, case_id=None) -> list:
        return []

    def episodes(self, limit: Optional[int] = None) -> list:
        return []

    def episode(self, episode_id: str) -> None:
        return None

    def update_grievance(self, grievance_id: str, status: str, **kwargs) -> None:
        return None

    def profiles(self) -> list:
        return []

    def profile(self, policy_no: str) -> None:
        return None

    def claims(self, policy_no: Optional[str] = None, limit: Optional[int] = None) -> list:
        return []

    def claim(self, claim_id: str) -> None:
        return None

    def claim_history(self, policy_no: str) -> list:
        return []

    def balances(self, policy_no: Optional[str] = None) -> list:
        return []

    def grievances(self, open_only: bool = False) -> list:
        return []

    def grievance(self, grievance_id: str) -> None:
        return None

    def context(self, max_claims: int = 5, policy_no: Optional[str] = None) -> dict:
        from .context import build_context
        return build_context(self, max_claims, policy_no)

    def export(self) -> dict:
        return {"user_id": self.user_id, "consent": self.consent().to_dict(), "consent_log": [], "policies": [],
                "claims": [], "balances": [], "grievances": [], "episodes": []}

    def forget(self) -> dict[str, int]:
        return {t: 0 for t in USER_TABLES}


def merge_history(server_history: Iterable[dict], remembered: Iterable[dict]) -> list[dict]:
    """Claim history for the engine: ``get_claim_history``'s claims plus remembered ones it doesn't have.

    The server's record wins for a claim both know. Sorted by admission date.
    """
    merged = {c["claim_id"]: c for c in remembered}
    merged.update({c["claim_id"]: c for c in server_history})
    return sorted(merged.values(), key=lambda c: (str(c["admission"]), c["claim_id"]))


# ---------------------------------------------------------------------- row -> record


def _profile(r) -> PolicyProfile:
    return PolicyProfile(r["policy_no"], r["insurer"], r["product"], Decimal(r["sum_insured"]), r["period_start"],
                         r["period_end"], r["first_inception"], r["wording_uin"], r["source"], r["updated_at"])


def _claim(r) -> ClaimRecord:
    return ClaimRecord(r["claim_id"], r["policy_no"], r["admission"], r["discharge"], r["diagnosis"], r["procedure"],
                       r["status"], Decimal(r["claimed_amount"]), Decimal(r["insurer_paid"]),
                       _dec(r["policy_payable"]), _dec(r["disputable_amount"]), _dec(r["unverified_amount"]),
                       json.loads(r["verdicts"]), tuple(json.loads(r["disputable_rows"])), r["case_id"],
                       r["source"], r["created_at"], r["updated_at"])


def _balance(r) -> LimitBalance:
    return LimitBalance(r["policy_no"], r["period_start"], r["fact_id"], r["rule_ref"], Decimal(r["amount"]),
                        r["text"], r["claim_id"], r["recorded_at"])


def _grievance(r, events: list[GrievanceEvent]) -> GrievanceRecord:
    return GrievanceRecord(r["grievance_id"], r["claim_id"], r["policy_no"], r["status"],
                           tuple(json.loads(r["row_ids"])), _dec(r["disputable_amount"]), r["text_sha256"],
                           r["reference_no"], r["created_at"], r["updated_at"], tuple(events))


def _episode(r, score: Optional[float] = None) -> EpisodeRecord:
    return EpisodeRecord(r["episode_id"], r["case_id"], r["claim_id"], r["summary"], tuple(json.loads(r["topics"])),
                         int(r["turns"]), r["source"], r["created_at"], r["updated_at"], int(r["recall_count"]), score)
