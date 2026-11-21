"""Fingerprint of the task body a playbook was written for.

A playbook freezes the calls that satisfied one body. When the user edits the body, the
frozen calls answer a question nobody asks any more, so a replay compares this hash first
and a mismatch sends the run back to the agent.
"""

import hashlib
import json


def task_body_hash(body: str) -> str:
    """Stable digest of a task's body; its JSON envelope cannot equal the legacy {prompt, steps} one."""
    payload = json.dumps({"body": body}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()
