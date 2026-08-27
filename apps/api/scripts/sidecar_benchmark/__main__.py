"""Resource + concurrency benchmark for the embedding sidecar (#918).

Spawns the real sidecar (``app.services.embedding_sidecar.server:app``) as a
uvicorn subprocess under configurable ``MEMORY_ONNX_THREADS`` /
``MEMORY_EMBEDDING_SIDECAR_CONCURRENCY``, polls its RSS with psutil, drives
HTTP load with httpx, and writes one JSON file per scenario under
``results/<tag>/``.

Scenarios:
- batch_sweep        peak RSS + latency vs request batch size (OOM cliff)
- concurrency_sweep  throughput/latency vs client concurrency × ONNX threads
- rerank_sweep       latency vs document count for /rerank
- soak               mixed realistic load; RSS drift over time
- equivalence        chunked-vs-whole vector identity (quality gate)

Run from ``apps/api``::

    uv run python -m scripts.sidecar_benchmark --tag baseline
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import platform
import random
import socket
import sys
import threading
import time

import httpx
import psutil

RESULTS_DIR = Path(__file__).parent / "results"
API_ROOT = Path(__file__).resolve().parents[2]
PORT = 8201
BASE_URL = f"http://127.0.0.1:{PORT}"


def _free_port() -> int:
    """A currently-free loopback port, so concurrent benchmark runs never
    fight over a fixed one."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


EMBED_PATH = "/embed"
RERANK_PATH = "/rerank"

MODEL = os.getenv("GAIA_EMBEDDING_MODEL", "mixedbread-ai/mxbai-embed-large-v1")

_WORDS = [
    "meeting",
    "project",
    "deadline",
    "schedule",
    "remind",
    "tomorrow",
    "flight",
    "hotel",
    "booking",
    "invoice",
    "budget",
    "review",
    "doctor",
    "dentist",
    "appointment",
    "dog",
    "walking",
    "groceries",
    "recipe",
    "dinner",
    "workout",
    "gym",
    "presentation",
    "client",
    "email",
    "contract",
    "draft",
    "launch",
    "sprint",
    "retro",
    "standup",
    "design",
    "deploy",
    "release",
    "test",
    "bug",
    "fix",
    "report",
    "quarterly",
    "goals",
    "roadmap",
    "team",
    "offsite",
    "birthday",
    "gift",
    "anniversary",
    "trip",
    "visa",
    "passport",
    "insurance",
    "renewal",
    "subscription",
    "cancel",
    "upgrade",
    "plan",
]


def make_text(target_chars: int, rng: random.Random) -> str:
    """A deterministic-ish pseudo sentence blob of ~target_chars characters."""
    parts: list[str] = []
    size = 0
    while size < target_chars:
        word = rng.choice(_WORDS)
        parts.append(word)
        size += len(word) + 1
    return " ".join(parts)[:target_chars]


def make_texts(count: int, chars_each: int, seed: int = 7) -> list[str]:
    return [make_text(chars_each, random.Random(seed * 100_003 + i)) for i in range(count)]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return ordered[idx]


class RssMonitor:
    """Samples a process RSS on a background thread."""

    def __init__(self, pid: int) -> None:
        self._ps = psutil.Process(pid)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._series: list[tuple[float, float]] = []
        self._peak = 0.0
        self._t0 = time.monotonic()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                rss_mb = self._ps.memory_info().rss / 2**20
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break
            with self._lock:
                self._series.append((time.monotonic() - self._t0, rss_mb))
                self._peak = max(self._peak, rss_mb)
            time.sleep(0.1)

    def reset_peak(self) -> float:
        """Forget pre-scenario history; returns current RSS as the floor."""
        with self._lock:
            self._series.clear()
            self._peak = 0.0
        return self.rss_mb()

    def peak_mb(self) -> float:
        with self._lock:
            return max(self._peak, self.rss_mb())

    def series(self) -> list[tuple[float, float]]:
        with self._lock:
            return list(self._series)

    def rss_mb(self) -> float:
        try:
            return self._ps.memory_info().rss / 2**20
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 0.0

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)


class Sidecar:
    """A sidecar subprocess under explicit resource knobs."""

    def __init__(self, tag: str, threads: int, concurrency: int) -> None:
        self.tag = tag
        self.threads = threads
        self.concurrency = concurrency
        self.port = _free_port()
        self.proc: asyncio.subprocess.Process | None = None
        self.monitor: RssMonitor | None = None

    async def start(self) -> None:
        assert self.proc is None
        env = dict(os.environ)
        env["MEMORY_ONNX_THREADS"] = str(self.threads)
        env["MEMORY_EMBEDDING_SIDECAR_CONCURRENCY"] = str(self.concurrency)
        env["GAIA_SERVICE_NAME"] = "embedding-sidecar-bench"
        env.setdefault("LOG_FORMAT", "json")
        cmd = [
            sys.executable,
            "-m",
            "uvicorn",
            "app.services.embedding_sidecar.server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--log-level",
            "warning",
        ]
        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=API_ROOT,
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.STDOUT,
        )
        assert self.proc.pid is not None
        global BASE_URL
        BASE_URL = f"http://127.0.0.1:{self.port}"
        self.monitor = RssMonitor(self.proc.pid)
        deadline = time.monotonic() + 600  # first boot downloads ~1.85GB of weights
        async with httpx.AsyncClient() as client:
            while time.monotonic() < deadline:
                if self.proc.returncode is not None:
                    raise RuntimeError(f"sidecar exited early rc={self.proc.returncode}")
                try:
                    response = await client.get(f"{BASE_URL}/health", timeout=2.0)
                    if response.status_code == 200:
                        await asyncio.sleep(0.5)
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(0.5)
        raise TimeoutError("sidecar did not become healthy in 600s")

    async def warmup(self) -> None:
        async with httpx.AsyncClient(timeout=120.0) as client:
            embed = await client.post(f"{BASE_URL}/embed", json={"texts": make_texts(8, 400)})
            rerank = await client.post(
                f"{BASE_URL}/rerank", json={"query": "q", "documents": make_texts(4, 200)}
            )
        # A failed warmup would poison every measurement after it — fail now.
        embed.raise_for_status()
        rerank.raise_for_status()

    async def stop(self) -> None:
        if self.monitor:
            self.monitor.stop()
            self.monitor = None
        if self.proc and self.proc.returncode is None:
            self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), timeout=10)
            except TimeoutError:
                self.proc.kill()
                await self.proc.wait()
        self.proc = None


@asynccontextmanager
async def running_sidecar(tag: str, threads: int, concurrency: int) -> AsyncIterator[Sidecar]:
    sidecar = Sidecar(tag, threads, concurrency)
    try:
        await sidecar.start()
        await sidecar.warmup()
        yield sidecar
    finally:
        await sidecar.stop()


async def timed_post(client: httpx.AsyncClient, path: str, payload: dict) -> tuple[float, dict]:
    started = time.perf_counter()
    response = await client.post(f"{BASE_URL}{path}", json=payload, timeout=300.0)
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.raise_for_status()
    return elapsed_ms, response.json()


async def post_status(client: httpx.AsyncClient, path: str, payload: dict) -> tuple[float, int]:
    """Like timed_post but returns the status instead of raising on 4xx."""
    started = time.perf_counter()
    response = await client.post(f"{BASE_URL}{path}", json=payload, timeout=300.0)
    return (time.perf_counter() - started) * 1000, response.status_code


def save_result(tag: str, scenario: str, data: dict) -> Path:
    out_dir = RESULTS_DIR / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{scenario}.json"
    path.write_text(json.dumps(data, indent=2))
    print(f"[saved] {path}")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


async def scenario_batch_sweep(sidecar: Sidecar) -> dict:
    """Peak RSS + latency as one request's batch grows — finds the OOM cliff."""
    monitor = sidecar.monitor
    assert monitor is not None
    sizes = [8, 32, 64, 128, 256, 512, 1024]
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=300.0) as client:
        for size in sizes:
            texts = make_texts(size, 1600)
            floor_mb = monitor.reset_peak()
            await asyncio.sleep(0.3)
            latencies: list[float] = []
            vectors_len = 0
            for _ in range(2):
                ms, body = await timed_post(client, EMBED_PATH, {"texts": texts})
                latencies.append(ms)
                vectors_len = len(body["vectors"])
            rows.append(
                {
                    "texts": size,
                    "chars_each": 1600,
                    "latency_ms_p50": round(percentile(latencies, 50), 1),
                    "latency_ms_max": round(max(latencies), 1),
                    "peak_rss_mb": round(monitor.peak_mb(), 1),
                    "rss_floor_mb": round(floor_mb, 1),
                    "vectors_returned": vectors_len,
                }
            )
            print(rows[-1])
    # Single huge text: post-fix this is rejected 413 by the sidecar guard
    # (pre-fix it went through, costing tokenization of far beyond the
    # model's 512-token window). Record whichever behavior is active.
    floor_mb = monitor.reset_peak()
    huge = ["x" * 200_000]
    async with httpx.AsyncClient(timeout=300.0) as client:
        ms_huge, status = await post_status(client, EMBED_PATH, {"texts": huge})
    rows.append(
        {
            "texts": 1,
            "chars_each": 200_000,
            "latency_ms_p50": round(ms_huge, 1),
            "latency_ms_max": round(ms_huge, 1),
            "peak_rss_mb": round(monitor.peak_mb(), 1),
            "rss_floor_mb": round(floor_mb, 1),
            "vectors_returned": 1 if status == 200 else 0,
            "status": status,
        }
    )
    return {"rows": rows}


async def scenario_concurrency_sweep(tag: str) -> dict:
    """Fixed total work at increasing client concurrency × ONNX thread budgets."""
    grid_threads = (
        [int(t) for t in os.getenv("BENCH_THREADS").split(",")]
        if os.getenv("BENCH_THREADS")
        else [2, 4]
    )
    grid_conc = (
        [int(c) for c in os.getenv("BENCH_CONC").split(",")]
        if os.getenv("BENCH_CONC")
        else [1, 2, 3, 4, 6, 8]
    )
    req_count, batch_texts, chars_each = 128, 16, 400
    payloads = [{"texts": make_texts(batch_texts, chars_each, seed=i)} for i in range(req_count)]
    rows: list[dict] = []
    for threads in grid_threads:
        for conc in grid_conc:
            async with running_sidecar(tag, threads, conc) as sidecar:
                monitor = sidecar.monitor
                assert monitor is not None
                monitor.reset_peak()
                latencies: list[float] = []
                failures: list[Exception] = []

                async def worker(
                    queue: asyncio.Queue,
                    client: httpx.AsyncClient,
                    out_latencies: list[float],
                    out_failures: list[Exception],
                ) -> None:
                    while True:
                        payload = await queue.get()
                        try:
                            ms, _ = await timed_post(client, EMBED_PATH, payload)
                            out_latencies.append(ms)
                        except Exception as exc:  # keep draining; reported after join
                            out_failures.append(exc)
                        finally:
                            queue.task_done()

                queue: asyncio.Queue = asyncio.Queue()
                for payload in payloads:
                    queue.put_nowait(payload)
                wall_start = time.perf_counter()
                async with httpx.AsyncClient(
                    timeout=300.0, limits=httpx.Limits(max_connections=conc + 4)
                ) as client:
                    workers = [
                        asyncio.create_task(worker(queue, client, latencies, failures))
                        for _ in range(conc)
                    ]
                    await queue.join()
                    for task in workers:
                        task.cancel()
                if failures:
                    raise failures[0]
                wall_s = time.perf_counter() - wall_start
                row = {
                    "threads": threads,
                    "concurrency": conc,
                    "requests": req_count,
                    "texts_per_request": batch_texts,
                    "wall_s": round(wall_s, 2),
                    "req_per_s": round(req_count / wall_s, 2),
                    "texts_per_s": round(req_count * batch_texts / wall_s, 1),
                    "latency_ms_p50": round(percentile(latencies, 50), 1),
                    "latency_ms_p95": round(percentile(latencies, 95), 1),
                    "latency_ms_p99": round(percentile(latencies, 99), 1),
                    "peak_rss_mb": round(monitor.peak_mb(), 1),
                }
                rows.append(row)
                print(row)
                save_result(tag, "concurrency_sweep_partial", {"rows": rows})
    return {"rows": rows, "workload": {"requests": req_count, "texts_per_request": batch_texts}}


async def scenario_rerank_sweep(sidecar: Sidecar) -> dict:
    monitor = sidecar.monitor
    assert monitor is not None
    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=300.0) as client:
        for docs in [10, 30, 60, 120, 240]:
            documents = make_texts(docs, 400)
            monitor.reset_peak()
            latencies = [
                (
                    await timed_post(
                        client,
                        RERANK_PATH,
                        {"query": "what was decided about the launch", "documents": documents},
                    )
                )[0]
                for _ in range(3)
            ]
            rows.append(
                {
                    "documents": docs,
                    "latency_ms_p50": round(percentile(latencies, 50), 1),
                    "peak_rss_mb": round(monitor.peak_mb(), 1),
                }
            )
            print(rows[-1])
    return {"rows": rows}


async def scenario_soak(sidecar: Sidecar, duration_s: float = 150.0) -> dict:
    """Mixed realistic traffic; watches RSS for drift/growth."""
    monitor = sidecar.monitor
    assert monitor is not None
    monitor.reset_peak()
    queries = make_texts(64, 80, seed=99)
    batches = [make_texts(16, 400, seed=1000 + i) for i in range(16)]
    rerank_docs = make_texts(30, 400, seed=55)
    stats = {"embed_query": [], "embed_batch": [], "rerank": []}
    deadline = time.monotonic() + duration_s

    async with httpx.AsyncClient(timeout=300.0) as client:

        async def worker(rng: random.Random) -> None:
            while time.monotonic() < deadline:
                roll = rng.random()
                if roll < 0.7:
                    ms, _ = await timed_post(client, "/embed_query", {"text": rng.choice(queries)})
                    stats["embed_query"].append(ms)
                elif roll < 0.9:
                    ms, _ = await timed_post(client, EMBED_PATH, {"texts": rng.choice(batches)})
                    stats["embed_batch"].append(ms)
                else:
                    ms, _ = await timed_post(
                        client, RERANK_PATH, {"query": "launch decision", "documents": rerank_docs}
                    )
                    stats["rerank"].append(ms)

        rngs = [random.Random(i) for i in range(4)]
        await asyncio.gather(*(worker(rng) for rng in rngs))

    series = monitor.series()
    step = max(1, len(series) // 300)
    return {
        "duration_s": duration_s,
        "rss_series_mb": [[round(t, 1), round(rss, 1)] for t, rss in series[::step]],
        "peak_rss_mb": round(monitor.peak_mb(), 1),
        "final_rss_mb": round(series[-1][1] if series else 0.0, 1),
        "stats": {
            op: {
                "count": len(v),
                "p50_ms": round(percentile(v, 50), 1),
                "p95_ms": round(percentile(v, 95), 1),
            }
            for op, v in stats.items()
        },
    }


async def scenario_equivalence() -> dict:
    """Vectors embedded whole must match vectors embedded in small chunks."""
    texts = make_texts(200, 400, seed=42)
    async with httpx.AsyncClient(timeout=300.0) as client:
        _, whole = await timed_post(client, EMBED_PATH, {"texts": texts})
        chunked_vectors: list[list[float]] = []
        for start in range(0, len(texts), 32):
            _, body = await timed_post(client, EMBED_PATH, {"texts": texts[start : start + 32]})
            chunked_vectors.extend(body["vectors"])
    if len(whole["vectors"]) != len(chunked_vectors):
        raise AssertionError(
            f"vector count mismatch: whole={len(whole['vectors'])} chunked={len(chunked_vectors)}"
        )
    max_abs = 0.0
    min_cos = 1.0
    for whole_vec, chunk_vec in zip(whole["vectors"], chunked_vectors):
        for a, b in zip(whole_vec, chunk_vec):
            max_abs = max(max_abs, abs(a - b))
        dot = sum(a * b for a, b in zip(whole_vec, chunk_vec))
        norm_a = sum(a * a for a in whole_vec) ** 0.5
        norm_b = sum(b * b for b in chunk_vec) ** 0.5
        min_cos = min(min_cos, dot / (norm_a * norm_b))
    if min_cos <= 0.999999:
        raise AssertionError(f"equivalence FAILED: min cosine {min_cos}")
    result = {
        "n": len(texts),
        "max_abs_diff": max_abs,
        "min_cosine": round(min_cos, 9),
        "pass": True,
    }
    print(result)
    return result


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def run_suite(tag: str, scenarios: set[str]) -> None:
    meta = {
        "tag": tag,
        "model": MODEL,
        "cpus": os.cpu_count(),
        "platform": platform.platform(),
        "fastembed_batch_default_note": "_embed_sync uses fastembed default batch_size=256",
    }

    if scenarios & {"batch_sweep", "rerank_sweep", "soak", "equivalence"}:
        async with running_sidecar(tag, threads=4, concurrency=3) as sidecar:
            if "batch_sweep" in scenarios:
                save_result(
                    tag, "batch_sweep", {"meta": meta, **await scenario_batch_sweep(sidecar)}
                )
            if "rerank_sweep" in scenarios:
                save_result(
                    tag, "rerank_sweep", {"meta": meta, **await scenario_rerank_sweep(sidecar)}
                )
            if "soak" in scenarios:
                data = await scenario_soak(sidecar)
                save_result(tag, "soak", {"meta": meta, **data})
            if "equivalence" in scenarios:
                save_result(tag, "equivalence", {"meta": meta, **await scenario_equivalence()})

    if "concurrency_sweep" in scenarios:
        save_result(
            tag, "concurrency_sweep", {"meta": meta, **await scenario_concurrency_sweep(tag)}
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="run label, e.g. baseline or fixed")
    parser.add_argument(
        "--scenarios",
        default="batch_sweep,rerank_sweep,soak,equivalence,concurrency_sweep",
        help="comma-separated subset to run",
    )
    args = parser.parse_args()
    wanted = {s.strip() for s in args.scenarios.split(",") if s.strip()}
    asyncio.run(run_suite(args.tag, wanted))


if __name__ == "__main__":
    main()
