"""Hold every catalog connector to real installs and real calls, on the E2B runner and the docker runner.

Run: mise connectors:conformance [connector ids ...] [--runner e2b|docker]. Team members run
it as `mise infisical connectors:conformance` so the team's keys apply. Per connector and
runner: install the pinned tools, prove a bad key is refused as an auth failure, then with a
real key verify, run one read, and where the provider has a safe sandbox create, delete and
confirm the deletion. A connector with no key is reported as skipped, naming the env var it
looked for; stripe-mock and LocalStack stand in for Stripe and AWS on the docker runner and
are reported as fakes. Not a CI lane. Exits 1 on any failure other than a known-dead team key.
"""

import argparse
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
import time

from app.config.connector_catalog import CONNECTOR_CATALOG
from app.models.connector_models import ConnectorSpec
from app.services.connectors.docker_runner import DockerConnectorRunner
from app.services.connectors.e2b_runner import E2BConnectorRunner
from app.services.connectors.runner import ConnectorRunner
from scripts.connectors.fakes import FakeName, running_fakes
from scripts.connectors.journeys import JOURNEYS, Journey, real_key
from scripts.connectors.stages import (
    Outcome,
    Stage,
    StageResult,
    Target,
    bad_key_stage,
    install_stage,
    read_stage,
    verify_stage,
    write_stage,
)

_E2B_PARALLEL = 3
_COLUMNS = (Stage.INSTALL, Stage.BAD_KEY, Stage.VERIFY, Stage.READ, Stage.WRITE)


class RunnerName(StrEnum):
    E2B = "e2b"
    DOCKER = "docker"


_RUNNERS: dict[RunnerName, Callable[[], ConnectorRunner]] = {
    RunnerName.E2B: E2BConnectorRunner,
    RunnerName.DOCKER: DockerConnectorRunner,
}


@dataclass(frozen=True)
class Row:
    connector_id: str
    runner: RunnerName
    results: dict[Stage, StageResult]
    known_dead_key: str | None


def _skip(stage: Stage, why: str) -> StageResult:
    return StageResult(stage, Outcome.SKIP, why)


def _target_for(
    journey: Journey, runner_name: RunnerName, runner: ConnectorRunner, fakes_up: set[FakeName]
) -> tuple[Target | None, str]:
    """Pick the real key, else the local fake, else say what is missing."""
    key, source = real_key(journey)
    if key is not None:
        return Target(runner, key), f"real key from {source}"
    fake = journey.fake
    if fake is None:
        return None, f"no credential ({source})"
    if runner_name is RunnerName.E2B:
        return None, f"no credential ({source}); the {fake.name} fake is local, E2B cannot reach it"
    if fake.name not in fakes_up:
        return None, f"no credential ({source}); the {fake.name} fake did not start"
    return Target(runner, fake.secret, fake.env, fake.args), f"fake: {fake.name}"


async def _keyed_stages(
    spec: ConnectorSpec, journey: Journey, target: Target, label: str, run_name: str
) -> dict[Stage, StageResult]:
    is_fake = target.fake_env is not None
    fake = journey.fake if is_fake else None
    verify_args = fake.verify_args if fake and fake.verify_args else None
    results = {Stage.VERIFY: await verify_stage(spec, target, verify_args)}
    read = journey.fake_read if is_fake and journey.fake_read else journey.read
    results[Stage.READ] = (
        await read_stage(spec, target, read, journey.read_expect)
        if read
        else _skip(Stage.READ, "no read journey")
    )
    write = journey.fake_write if is_fake and journey.fake_write else journey.write
    results[Stage.WRITE] = (
        await write_stage(spec, target, write, run_name)
        if write
        else _skip(Stage.WRITE, "no safe sandbox to write to")
    )
    if is_fake:
        results = {
            stage: StageResult(stage, r.outcome, f"{label}; {r.detail}")
            for stage, r in results.items()
        }
    return results


async def check(
    connector_id: str, spec: ConnectorSpec, runner_name: RunnerName, fakes_up: set[FakeName]
) -> Row:
    """Run every stage for one connector on one runner."""
    runner = _RUNNERS[runner_name]()
    journey = JOURNEYS.get(connector_id, Journey())
    results = {Stage.INSTALL: await install_stage(spec, runner)}
    results[Stage.BAD_KEY] = await bad_key_stage(spec, runner)
    target, label = _target_for(journey, runner_name, runner, fakes_up)
    run_name = f"gaia-conformance-{int(time.time())}-{runner_name}"
    if target is None:
        results |= {stage: _skip(stage, label) for stage in (Stage.VERIFY, Stage.READ, Stage.WRITE)}
    elif results[Stage.INSTALL].outcome is Outcome.FAIL:
        results |= {
            stage: _skip(stage, "install failed")
            for stage in (Stage.VERIFY, Stage.READ, Stage.WRITE)
        }
    else:
        results |= await _keyed_stages(spec, journey, target, label, run_name)
    return Row(connector_id, runner_name, results, journey.known_dead_key)


def _cell(result: StageResult) -> str:
    return result.outcome.value if result.outcome is not Outcome.FAIL else "FAIL"


def _print(rows: list[Row]) -> int:
    width = max(len(row.connector_id) for row in rows)
    print(f"\n{'connector':<{width}}  runner  " + "  ".join(f"{s.value:<15}" for s in _COLUMNS))
    for row in rows:
        cells = "  ".join(f"{_cell(row.results[s]):<15}" for s in _COLUMNS)
        print(f"{row.connector_id:<{width}}  {row.runner.value:<6}  {cells}")
    print("\nDetails:")
    failed = 0
    for row in rows:
        for stage in _COLUMNS:
            result = row.results[stage]
            known = row.known_dead_key and stage is not Stage.INSTALL and stage is not Stage.BAD_KEY
            if result.outcome is Outcome.FAIL and not known:
                failed += 1
            if result.outcome is not Outcome.PASS or result.detail:
                note = (
                    f" (known: {row.known_dead_key})"
                    if known and result.outcome is Outcome.FAIL
                    else ""
                )
                print(
                    f"  {row.connector_id} {row.runner} {stage}: {result.outcome} {result.detail}{note}"
                )
    print(f"\n{failed} failed" if failed else "\nno failures")
    return failed


async def _lane(jobs: list[Callable[[], Awaitable[Row]]], parallel: int) -> list[Row]:
    gate = asyncio.Semaphore(parallel)

    async def one(job: Callable[[], Awaitable[Row]]) -> Row:
        async with gate:
            return await job()

    return list(await asyncio.gather(*(one(job) for job in jobs)))


async def _main(only: list[str], runners: list[RunnerName]) -> int:
    catalog = {i.id: i.connector_config for i in CONNECTOR_CATALOG if i.connector_config}
    unknown = sorted(set(only) - set(catalog))
    if unknown:
        print(f"not in the catalog: {', '.join(unknown)}")
        return 1
    chosen = {cid: spec for cid, spec in catalog.items() if not only or cid in only}
    wanted_fakes = {
        j.fake.name for cid, j in JOURNEYS.items() if cid in chosen and j.fake is not None
    }
    use_fakes = wanted_fakes if RunnerName.DOCKER in runners else set()
    async with running_fakes(use_fakes) as fakes_up:
        lanes = [
            _lane(
                [
                    (lambda cid=cid, spec=spec, r=runner: check(cid, spec, r, fakes_up))
                    for cid, spec in chosen.items()
                ],
                _E2B_PARALLEL if runner is RunnerName.E2B else 1,
            )
            for runner in runners
        ]
        rows = [row for lane in await asyncio.gather(*lanes) for row in lane]
    rows.sort(key=lambda row: (row.connector_id, row.runner))
    return 1 if _print(rows) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("connectors", nargs="*", help="catalog ids to check (default: all)")
    parser.add_argument(
        "--runner", type=RunnerName, choices=list(RunnerName), help="one runner (default: both)"
    )
    args = parser.parse_args()
    runners = [args.runner] if args.runner else list(RunnerName)
    raise SystemExit(asyncio.run(_main(args.connectors, runners)))
