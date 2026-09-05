"""Drive the playbook surface against a running stack with the scripted model.

Boot the stack in sim mode first (the API with the dev auth bypass, the ARQ
worker, and ``tools/llm-stub``; see the ``driving-gaia`` skill), then::

    cd apps/api
    uv run --group backend python -m scripts.playbook_drive --worker-log /path/to/worker.log
    uv run --group backend python -m scripts.playbook_drive --only S9 X18

The worker's JSON log is where the playbook lifecycle says what each fire did,
so the drive has to be told where it is. Exit status is the number of failed
fires, so a CI lane can gate on it.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import sys
import time

from .client import DEFAULT_API, DEFAULT_USER, GaiaClient
from .observe import Store, WorkerLog, fire_and_observe
from .scenarios import SCENARIOS, Context, Scenario

FIRST_PENDING = "${FIRST_PENDING}"


@dataclass(frozen=True)
class Verdict:
    scenario: str
    fire: str
    ok: bool
    why: str
    detail: str


def run_scenario(
    scenario: Scenario, client: GaiaClient, store: Store, log: WorkerLog, user_id: str
) -> list[Verdict]:
    stamp = time.strftime("%H:%M:%S")
    print(f"{stamp} {scenario.key} {scenario.title}", flush=True)
    seed = Context(client=client, store=store, user_id=user_id, workflow_id="")
    if scenario.before is not None:
        scenario.before(seed)
    body = scenario.script
    if FIRST_PENDING in body:
        pending = client.pending_todos()
        if not pending:
            raise RuntimeError(f"{scenario.key} needs a pending todo before it is created")
        body = body.replace(FIRST_PENDING, pending[0].id)
    # Creating a workflow counts against the same tiered limits a fire does.
    store.reset_rate_limits(user_id)
    workflow = client.create_workflow(f"{scenario.key} {scenario.title}", body, scenario.category)
    ctx = Context(
        client=client,
        store=store,
        user_id=user_id,
        workflow_id=workflow.id,
        marks=dict(seed.marks),
    )
    verdicts: list[Verdict] = []
    for fire in scenario.fires:
        if fire.before is not None:
            fire.before(ctx)
        try:
            observation = fire_and_observe(client, store, log, workflow.id, user_id=user_id)
        except (TimeoutError, RuntimeError) as error:
            verdicts.append(Verdict(scenario.key, fire.name, False, fire.why, str(error)))
            print(f"  FAIL {fire.name}: {error}", flush=True)
            break
        ok = fire.expect(observation, ctx)
        detail = observation.model_dump_json(exclude={"warnings", "errors"})
        verdicts.append(Verdict(scenario.key, fire.name, ok, fire.why, detail))
        print(f"  {'PASS' if ok else 'FAIL'} {fire.name}", flush=True)
        if not ok:
            print(f"       expected: {fire.why}", flush=True)
            print(f"       observed: {detail[:600]}", flush=True)
    return verdicts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--worker-log", type=Path, required=True)
    parser.add_argument("--only", nargs="*", default=[], metavar="KEY")
    parser.add_argument("--out", type=Path, default=Path("playbook_drive.results.json"))
    args = parser.parse_args(argv)

    client = GaiaClient(args.api, args.user)
    user = client.mint_user()
    store = Store()
    log = WorkerLog(args.worker_log)
    chosen = [s for s in SCENARIOS if not args.only or s.key in args.only]
    if not chosen:
        parser.error(f"no scenario matches {args.only}; keys: {[s.key for s in SCENARIOS]}")

    verdicts: list[Verdict] = []
    for scenario in chosen:
        verdicts.extend(run_scenario(scenario, client, store, log, user.id))

    failed = [v for v in verdicts if not v.ok]
    args.out.write_text(json.dumps([v.__dict__ for v in verdicts], indent=1))
    print(f"\n{len(verdicts) - len(failed)}/{len(verdicts)} fires passed; results in {args.out}")
    for verdict in failed:
        print(f"  FAIL {verdict.scenario}: {verdict.fire} ({verdict.why})")
    return len(failed)


if __name__ == "__main__":
    sys.exit(main())
