"""The memory store on PostgreSQL: the same tests as on SQLite, plus what only PostgreSQL needs.

Runs against deploy/storage.compose.yml when CLAIMCLEAR_TEST_POSTGRES is set, e.g.

    CLAIMCLEAR_TEST_POSTGRES=postgresql://claimclear:claimclear@127.0.0.1:5432/claimclear

and is skipped otherwise. Every test gets its own schema, dropped afterwards.

The 36 tests imported from test_memory.py are the ones that use the store only through its
API (the other 8 open the SQLite file directly); here they run on PostgreSQL fixtures.
"""

import os
import uuid

import pytest

from claimclear_memory import MemoryStore, Retention
from claimclear_memory.db import Database
from test_memory import (  # noqa: F401  the shared tests, collected again with this module's fixtures
    SET01,
    Clock,
    consented,
    test_a_later_claim_updates_the_balance_but_an_earlier_one_does_not,
    test_balances_come_from_the_engines_remaining_facts,
    test_balances_follow_the_current_policy_period,
    test_claim_history_in_the_engines_shape,
    test_consent_is_recorded,
    test_context_for_one_policy,
    test_context_for_the_agents,
    test_context_is_bounded,
    test_context_purges_before_the_agents_see_it,
    test_expiry_drops_balances_of_a_past_policy_period,
    test_expiry_job_for_every_user,
    test_expiry_keeps_recent_data,
    test_expiry_never_touches_open_grievances,
    test_expiry_of_claims_waits_for_their_grievances,
    test_grievance_lifecycle,
    test_grievance_transitions_are_enforced,
    test_grievances_only_on_rows_the_audit_found_disputable,
    test_memory_off_stores_nothing,
    test_merge_history_prefers_the_server_record,
    test_nothing_is_stored_without_consent,
    test_older_claims_are_summarised_without_amounts,
    test_refuses_an_audit_that_is_not_final,
    test_refuses_mismatched_inputs,
    test_rejection_letter_is_remembered_as_rejected,
    test_remember_claim_from_the_audit,
    test_remembering_again_updates_and_keeps_created_at,
    test_render_for_a_prompt,
    test_render_keeps_to_its_budget,
    test_session_memory_follows_consent_and_the_switch,
    test_users_never_see_each_other,
    test_user_ids_are_validated,
    test_withdrawing_but_keeping_the_data,
    test_withdrawing_consent_deletes_by_default,
)

PG = os.environ.get("CLAIMCLEAR_TEST_POSTGRES")
pytestmark = pytest.mark.skipif(not PG, reason="set CLAIMCLEAR_TEST_POSTGRES (see deploy/storage.compose.yml)")


@pytest.fixture
def pg_url():
    schema = "mem_" + uuid.uuid4().hex[:10]
    url = f"{PG}{'&' if '?' in PG else '?'}schema={schema}"
    yield url
    db = Database(url)
    with db.connect() as con:
        con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(pg_url, clock):
    return MemoryStore(pg_url, clock=clock)


@pytest.fixture
def mem(store):
    m = consented(store, "u_alice")
    m.remember_claim(SET01["case"], SET01["audit"], case_id="case_0123456789abcdef", letter=SET01["letter"])
    return m


@pytest.fixture
def short(pg_url, clock):
    return MemoryStore(pg_url, clock=clock,
                       retention=Retention(claims_days=30, closed_grievance_days=10, inactive_days=1000))


# --------------------------------------------------------------------------- PostgreSQL only


def test_the_store_is_on_postgres(store):
    assert store.db.postgres and store.path is None


def test_data_survives_reopening_on_postgres(mem, pg_url):
    again = MemoryStore(pg_url).for_user("u_alice")
    assert [c.claim_id for c in again.claims()] == [c.claim_id for c in mem.claims()]


def test_export_and_forget_on_postgres(mem, pg_url):
    exported = mem.export()
    assert exported["claims"] and exported["policies"]
    deleted = mem.forget()
    assert deleted["claims"] == 1
    assert MemoryStore(pg_url).for_user("u_alice").export()["claims"] == []


def test_schema_version_is_checked_on_postgres(store, pg_url):
    with store.connect() as con:
        con.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    with pytest.raises(Exception) as e:
        MemoryStore(pg_url)
    assert getattr(e.value, "code", "") == "SCHEMA_VERSION"
