"""ClaimClear input security (threat model T1, T2): guards on uploaded documents and chat messages.

Settings (``ClaimClear/.env``):
    CLAIMCLEAR_DEFENCES=on|off              the E2 switch (default on)
    CLAIMCLEAR_GUARDS=rules,safeguard       which guards run: rules, llm, safeguard, llamaguard, nemotron

Guards (all ``InputGuard``): ``rules`` keywords · ``llm`` our model with our policy · ``safeguard`` /
``llamaguard`` / ``nemotron`` guard models on OpenRouter. Uploads are checked and cleaned before they are stored
(``checks.check_files``); chat messages are checked before the answerer sees them (``checks.check_chat``); the user is
told what was found (``messages``).
"""
from .input_guard import InputGuard, Finding
from .checks import GUARDS, FileCheck, build, check_chat, check_file, check_files, chosen, enabled
from .messages import chat_reply, files_message, guard_problems

__all__ = ["InputGuard", "Finding", "FileCheck", "GUARDS", "build", "chosen", "enabled", "check_file",
           "check_files", "check_chat", "files_message", "chat_reply", "guard_problems"]
