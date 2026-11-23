"""claimclear_memory: ClaimClear's long-term memory, with consent, expiry and trimming.

Per user: the policy profile, verified claims, the engine's sub-limit balances,
and grievance status. SQLite, standard library only, so it runs in the agents'
and the app's environments alike.

    from claimclear_memory import MemoryStore, merge_history, render

    store = MemoryStore()
    store.for_user(user_id).grant_consent("app:settings")     # the user's own choice, in the app
    mem = store.session_memory(user_id)                        # NoMemory unless consented and switched on
    state["memory"] = mem.context()                            # at the start of a session (expired data purged)
    history = merge_history(server_history, mem.claim_history(policy_no))
    mem.remember_claim(case, letter_audit, case_id=case_id, letter=letter)   # after the critic passes
    mem.remember_conversation(chat_turns, case_id=case_id)    # episodic: topics only, amounts scrubbed
    mem.recall("what did I ask about the co-pay?")             # hybrid search over earlier conversations

Memory never computes money, is written only from tool results, and follows
additional_resources/member2_knowledge_memory_tools/memory_policy.md (``POLICY_VERSION``).
"""

from .context import build_context, render
from .episodes import HashingEmbedder, UnsafeSummary, extractive_summary, render_episodes, scrub
from .models import (ClaimRecord, EpisodeRecord, GrievanceEvent, GrievanceRecord, GrievanceStatus, LimitBalance,
                     PolicyProfile)
from .store import (
    DB_ENV,
    POLICY_VERSION,
    ConsentStatus,
    MemoryStore,
    MemoryStoreError,
    NoMemory,
    Retention,
    UserMemory,
    default_db_path,
    merge_history,
)

__all__ = ["ClaimRecord", "ConsentStatus", "DB_ENV", "EpisodeRecord", "GrievanceEvent", "GrievanceRecord",
           "GrievanceStatus", "HashingEmbedder", "LimitBalance", "MemoryStore", "MemoryStoreError", "NoMemory",
           "POLICY_VERSION", "PolicyProfile", "Retention", "UnsafeSummary", "UserMemory", "build_context",
           "default_db_path", "extractive_summary", "merge_history", "render", "render_episodes", "scrub"]
