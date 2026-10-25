"""deploy.sh notify and verify-commit, against a real local HTTP server.

notify used to post to Discord alone, so a failed deploy never reached the
Slack channel Grafana alerts land in. verify-commit is the check that prod
actually serves the image the deploy rolled out. Only ``docker`` is stubbed
(the image config read); curl, jq and the HTTP round trips are real.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import textwrap
import threading
from typing import Any

import pytest

SCRIPT = Path(__file__).parent.parent / "deploy.sh"
APPS_SHA = "0123456789abcdef0123456789abcdef01234567"
BOTS_SHA = "fedcba9876543210fedcba9876543210fedcba98"
BOTS = ("discord", "slack", "telegram", "whatsapp", "imessage")


@dataclass
class Sink:
    """Serves canned GET bodies by path and records every POST."""

    url: str
    bodies: dict[str, dict[str, object]] = field(default_factory=dict)
    status: dict[str, int] = field(default_factory=dict)
    # Decoded webhook JSON: its shape is what the tests assert, not something to pre-declare.
    posts: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


@pytest.fixture
def sink() -> Iterator[Sink]:
    state = Sink(url="")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_: object) -> None:
            pass

        def _reply(self, path: str, default: dict[str, object]) -> None:
            body = json.dumps(state.bodies.get(path, default)).encode()
            self.send_response(state.status.get(path, 200))
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            self._reply(self.path, {"status": "ok"})

        def do_POST(self) -> None:
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            state.posts.append((self.path, json.loads(raw)))
            self._reply(self.path.split("?")[0], {"id": "1", "channel_id": "42"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield state
    server.shutdown()


def image_json(
    env: list[str], platforms: tuple[str, ...] = ("linux/amd64", "linux/arm64")
) -> object:
    """Build what imagetools inspect's {{json .Image}} prints: one config, or one per platform."""
    config = {"architecture": "amd64", "os": "linux", "config": {"Env": env}}
    return config if not platforms else dict.fromkeys(platforms, config)


def fake_docker(tmp_path: Path, images: dict[str, object]) -> Path:
    """`docker buildx imagetools inspect <repo>:<tag> --format '{{json .Image}}'` prints that repo's image."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for repo, image in images.items():
        (tmp_path / f"image-{repo}.json").write_text(json.dumps(image))
    stub = bin_dir / "docker"
    stub.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            [[ "$6" == '{{{{json .Image}}}}' ]] || {{ echo "unexpected format: $6" >&2; exit 2; }}
            ref="$4"; repo="${{ref##*/}}"; repo="${{repo%%:*}}"
            cat "{tmp_path}/image-$repo.json"
            """
        )
    )
    stub.chmod(0o755)
    return bin_dir


def run(
    tmp_path: Path, sub: str, extra: dict[str, str], bin_dir: Path | None = None
) -> tuple[subprocess.CompletedProcess[str], str]:
    output = tmp_path / "github_output"
    output.touch()
    path = os.environ["PATH"] if bin_dir is None else f"{bin_dir}:{os.environ['PATH']}"
    env = {"PATH": path, "HOME": os.environ.get("HOME", "/tmp"), "GITHUB_OUTPUT": str(output)}
    proc = subprocess.run(
        ["bash", str(SCRIPT), sub],
        env=env | extra,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc, output.read_text()


NOTIFY = {"MESSAGE": "**Backend Deploy Failed**\n**Commit:** `abc`", "COLOR": "#ff6b6b"}


def test_notify_posts_to_discord_and_slack(tmp_path: Path, sink: Sink) -> None:
    proc, _ = run(
        tmp_path,
        "notify",
        NOTIFY | {"DISCORD_WEBHOOK": f"{sink.url}/discord", "SLACK_WEBHOOK": f"{sink.url}/slack"},
    )

    assert proc.returncode == 0, proc.stderr
    by_path = {path.split("?")[0]: (path, body) for path, body in sink.posts}
    discord_path, discord = by_path["/discord"]
    assert "wait=true" in discord_path
    assert discord["embeds"][0]["description"].startswith("**Backend Deploy Failed**")
    assert discord["embeds"][0]["color"] == 0xFF6B6B
    slack = by_path["/slack"][1]["attachments"][0]
    assert slack["color"] == "#ff6b6b"
    assert slack["text"].startswith("*Backend Deploy Failed*\n*Commit:* `abc`")
    assert "channel 42" in proc.stdout


def test_notify_still_sends_discord_but_fails_when_slack_is_unset(
    tmp_path: Path, sink: Sink
) -> None:
    proc, _ = run(tmp_path, "notify", NOTIFY | {"DISCORD_WEBHOOK": f"{sink.url}/discord"})

    assert proc.returncode != 0
    assert [p.split("?")[0] for p, _ in sink.posts] == ["/discord"]
    assert "SLACK_WEBHOOK" in proc.stdout + proc.stderr


def test_notify_fails_when_a_webhook_rejects(tmp_path: Path, sink: Sink) -> None:
    sink.status["/slack"] = 404
    proc, _ = run(
        tmp_path,
        "notify",
        NOTIFY | {"DISCORD_WEBHOOK": f"{sink.url}/discord", "SLACK_WEBHOOK": f"{sink.url}/slack"},
    )

    assert proc.returncode != 0
    assert "HTTP 404" in proc.stdout + proc.stderr


def verify_env(sink: Sink, bots_tag: str = "") -> dict[str, str]:
    return {
        "PROD_ORIGIN": sink.url,
        "APPS_IMAGE_TAG": "2610.14.0123456",
        "BOTS_IMAGE_TAG": bots_tag,
        "VERIFY_TIMEOUT_SECS": "2",
        "VERIFY_POLL_SECS": "0",
    }


def images(tmp_path: Path) -> Path:
    found: dict[str, object] = {"gaia": image_json(["PATH=/bin", f"GIT_COMMIT_SHA={APPS_SHA}"])}
    found |= {f"gaia-bot-{bot}": image_json([f"GIT_COMMIT_SHA={BOTS_SHA}"]) for bot in BOTS}
    return fake_docker(tmp_path, found)


def test_verify_commit_passes_when_prod_serves_the_deployed_image(
    tmp_path: Path, sink: Sink
) -> None:
    sink.bodies["/health"] = {"status": "online", "commit": APPS_SHA[:8]}

    proc, output = run(tmp_path, "verify-commit", verify_env(sink), images(tmp_path))

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"commit={APPS_SHA}" in output.splitlines()


def test_verify_commit_fails_loud_when_prod_serves_another_commit(
    tmp_path: Path, sink: Sink
) -> None:
    sink.bodies["/health"] = {"status": "online", "commit": "deadbeef"}

    proc, _ = run(tmp_path, "verify-commit", verify_env(sink), images(tmp_path))

    assert proc.returncode != 0
    assert "::error::" in proc.stdout + proc.stderr
    assert "deadbeef" in proc.stdout + proc.stderr
    assert APPS_SHA[:8] in proc.stdout + proc.stderr


def test_verify_commit_checks_every_bot_when_bots_were_deployed(tmp_path: Path, sink: Sink) -> None:
    sink.bodies["/health"] = {"commit": APPS_SHA[:8]}
    for bot in BOTS:
        sink.bodies[f"/bots/{bot}/health"] = {"commit": BOTS_SHA[:8]}
    sink.bodies["/bots/slack/health"] = {"commit": "local"}

    proc, _ = run(tmp_path, "verify-commit", verify_env(sink, "2610.14.fedcba9"), images(tmp_path))

    assert proc.returncode != 0
    assert "/bots/slack/health" in proc.stdout + proc.stderr


def test_verify_commit_fails_when_the_image_carries_no_commit(tmp_path: Path, sink: Sink) -> None:
    sink.bodies["/health"] = {"commit": "local"}
    bin_dir = fake_docker(tmp_path, {"gaia": image_json(["PATH=/bin"])})

    proc, _ = run(tmp_path, "verify-commit", verify_env(sink), bin_dir)

    assert proc.returncode != 0
    assert "GIT_COMMIT_SHA" in proc.stdout + proc.stderr


def test_verify_commit_reads_a_single_platform_image(tmp_path: Path, sink: Sink) -> None:
    sink.bodies["/health"] = {"commit": APPS_SHA[:8]}
    bin_dir = fake_docker(tmp_path, {"gaia": image_json([f"GIT_COMMIT_SHA={APPS_SHA}"], ())})

    proc, output = run(tmp_path, "verify-commit", verify_env(sink), bin_dir)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"commit={APPS_SHA}" in output.splitlines()


def test_verify_commit_fails_when_an_index_s_platforms_disagree_on_the_commit(
    tmp_path: Path, sink: Sink
) -> None:
    sink.bodies["/health"] = {"commit": APPS_SHA[:8]}
    index = {
        "linux/amd64": {"config": {"Env": [f"GIT_COMMIT_SHA={APPS_SHA}"]}},
        "linux/arm64": {"config": {"Env": [f"GIT_COMMIT_SHA={BOTS_SHA}"]}},
    }
    bin_dir = fake_docker(tmp_path, {"gaia": index})

    proc, _ = run(tmp_path, "verify-commit", verify_env(sink), bin_dir)

    assert proc.returncode != 0
    assert "platforms disagree" in proc.stdout + proc.stderr
