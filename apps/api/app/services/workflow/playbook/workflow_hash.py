"""Fingerprint of the workflow a playbook was written for.

A playbook freezes the sequence that satisfied one particular prompt and set of
steps. When the user edits either, the frozen sequence answers a question nobody
asked any more, so the hash is compared before a replay and a mismatch sends the
run back to the agent instead of replaying something stale.
"""

from collections.abc import Sequence
import hashlib
import json

from app.models.workflow_models import WorkflowStep


def workflow_hash(prompt: str, steps: Sequence[WorkflowStep]) -> str:
    """Stable digest of a workflow's prompt plus steps. Key order is canonical so
    the same workflow hashes identically across processes and restarts."""
    # Every WorkflowStep field is str, so json and python dumps are byte
    # identical and the mode value is provably unobservable here.
    dumped = [step.model_dump(mode="json") for step in steps]  # pragma: no mutate
    payload = json.dumps(
        {"prompt": prompt, "steps": dumped},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()
