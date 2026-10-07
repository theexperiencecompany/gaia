"""The agents' home: hooks config, the per-sandbox setup, the run seed, and the save/hook scripts.

The shell scripts and the OpenCode plugin run for real here (bash, tar,
sqlite3, node) against temp dirs, with curl and the save stubbed by recording
scripts. Not exercised: E2B, JuiceFS latency, the CLIs actually firing hooks.
"""

import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import sqlite3
import subprocess
import tarfile
import textwrap
from unittest.mock import patch

import pytest

from app.services.agent_lab import agents_home, sandbox_setup
from app.services.agent_lab.agents_home import (
    AGENTS_HOME,
    AGENTS_SAVE,
    CLAUDE_SETTINGS_PATH,
    HOOK_SCRIPT,
    HOOK_TIMEOUT_SECONDS,
    OPENCODE_CONFIG_DIR,
    RESTORED_MARKER,
    SAVE_EXCLUDES,
    SAVE_SCRIPT,
    build_agents_setup_command,
    render_vendored,
    restored_from,
)
from app.services.agent_lab.lab_runs import run_dir
from app.services.agent_lab.sandbox_setup import (
    LAB_CALLBACK_URL_VAR,
    LAB_RUN_ID_VAR,
    LAB_TOKEN_VAR,
    build_seed_command,
    lab_env_path,
    mint_lab_hooks_token,
)
from app.services.sandbox import execute_token
from app.utils.errors import AppError

SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"
EVENTS_URL = "https://api.test.example/api/v1/lab/events"
RUN_ID = "lab-run-1"
HOME = AGENTS_HOME.rsplit("/agents", 1)[0]


def _decoded_writes(command: str) -> dict[str, str]:
    """Return every file the command writes through base64, keyed by its path."""
    writes = {}
    for step in command.split(" && "):
        if not step.startswith("echo '") or "| base64 -d >" not in step:
            continue
        encoded = step[len("echo '") : step.index("' | base64 -d")]
        path = shlex.split(step.split("| base64 -d ", 1)[1].lstrip(">").strip())[0]
        writes[path] = base64.b64decode(encoded).decode()
    return writes


def _hook_handlers(settings_text: str) -> list[dict[str, object]]:
    settings = json.loads(settings_text)
    return [h for groups in settings["hooks"].values() for g in groups for h in g["hooks"]]


def _local(path: str, root: Path) -> str:
    """Map the sandbox home and /workspace into a temp root, as FakeAsyncSandbox does."""
    return path.replace(HOME, str(root / "home")).replace("/workspace", str(root / "workspace"))


def _host_shims(bin_dir: Path) -> None:
    """Stand in for Linux tools macOS lacks (flock, timeout); the sandbox and CI have the real ones."""
    if shutil.which("flock") is None:
        _executable(bin_dir / "flock", "#!/usr/bin/env bash\nexit 0\n")
    if shutil.which("timeout") is None:
        _executable(bin_dir / "timeout", '#!/usr/bin/env bash\nshift\nexec "$@"\n')


def _host_env(shims: Path) -> dict[str, str]:
    """Return an env with the shims first; macOS tar otherwise adds ._ AppleDouble entries."""
    return {**os.environ, "PATH": f"{shims}:{os.environ['PATH']}", "COPYFILE_DISABLE": "1"}


def _executable(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


@pytest.mark.unit
class TestClaudeHooksSettings:
    def _handlers(self) -> list[dict[str, object]]:
        return _hook_handlers(_decoded_writes(build_agents_setup_command())[CLAUDE_SETTINGS_PATH])

    def test_every_way_a_turn_ends_or_waits_runs_gaia_hook(self) -> None:
        """StopFailure is the API-error stop (expired login, rate limit); Stop never fires for it."""
        settings = json.loads(_decoded_writes(build_agents_setup_command())[CLAUDE_SETTINGS_PATH])
        assert set(settings["hooks"]) == {"Stop", "StopFailure", "Notification"}
        for event in ("Stop", "StopFailure", "Notification"):
            (group,) = settings["hooks"][event]
            assert "matcher" not in group, "one event must relay once, never twice"

    def test_each_handler_runs_the_hook_script_with_time_to_save(self) -> None:
        for handler in self._handlers():
            assert handler == {
                "type": "command",
                "command": HOOK_SCRIPT,
                "timeout": HOOK_TIMEOUT_SECONDS,
            }

    def test_shared_config_carries_no_host_or_token(self) -> None:
        """The run's URL and token come from the process env, so one config serves every run."""
        writes = _decoded_writes(build_agents_setup_command())
        for path in (CLAUDE_SETTINGS_PATH, f"{OPENCODE_CONFIG_DIR}/plugins/gaia_notify.js"):
            assert "://" not in writes[path].replace("node:child_process", "")


@pytest.mark.unit
class TestRenderVendored:
    def test_a_missing_placeholder_fails_loud(self) -> None:
        with pytest.raises(AppError):
            render_vendored("gaia_hook.sh", {"NOT_THERE": "x"})

    def test_an_unrendered_placeholder_fails_loud(self) -> None:
        with pytest.raises(AppError):
            render_vendored("gaia_hook.sh", {"SAVE_SCRIPT": SAVE_SCRIPT})


@pytest.mark.unit
class TestRunSeed:
    def test_run_folder_and_shared_home_live_on_local_disk(self) -> None:
        """On real E2B an OpenCode turn took ~2.5 min with its data on JuiceFS, ~10s locally."""
        for path in (run_dir(RUN_ID), AGENTS_HOME, CLAUDE_SETTINGS_PATH, OPENCODE_CONFIG_DIR):
            assert not path.startswith("/workspace")
        assert AGENTS_SAVE.startswith("/workspace/")

    def test_seed_carries_no_literal_host_or_token(self) -> None:
        command = build_seed_command(EVENTS_URL, "tok-1", RUN_ID)
        assert EVENTS_URL not in command
        assert "tok-1" not in command

    def test_seed_writes_the_run_env_as_a_sourceable_private_file(self) -> None:
        """A later bash call (resume) gets no env injected; it sources this file instead."""
        command = build_seed_command(EVENTS_URL, "tok-1", RUN_ID)
        assert f"chmod 600 {shlex.quote(lab_env_path(RUN_ID))}" in command
        sourced = subprocess.run(
            ["bash", "-c", "set -a; . /dev/stdin; set +a; env"],
            input=_decoded_writes(command)[lab_env_path(RUN_ID)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        for key, value in sandbox_setup.lab_env(EVENTS_URL, "tok-1", RUN_ID).items():
            assert f"{key}={value}" in sourced

    def test_run_env_names_the_run_and_the_shared_hooks(self) -> None:
        env = sandbox_setup.lab_env(EVENTS_URL, "tok-1", RUN_ID)
        assert env[LAB_CALLBACK_URL_VAR] == EVENTS_URL
        assert env[LAB_TOKEN_VAR] == "tok-1"
        assert env[LAB_RUN_ID_VAR] == RUN_ID
        assert env[sandbox_setup.LAB_CLAUDE_SETTINGS_VAR] == CLAUDE_SETTINGS_PATH
        assert env[sandbox_setup.OPENCODE_CONFIG_DIR_VAR] == OPENCODE_CONFIG_DIR

    def test_seed_requires_a_run_id(self) -> None:
        with pytest.raises(AppError):
            build_seed_command(EVENTS_URL, "tok-1", "")


@pytest.mark.unit
class TestAgentsSetup:
    """The per-sandbox setup, run through real bash in a temp home."""

    def _run(self, root: Path) -> subprocess.CompletedProcess[str]:
        bin_dir = root / "shims"
        _host_shims(bin_dir)
        return subprocess.run(
            ["bash", "-c", _local(build_agents_setup_command(), root)],
            capture_output=True,
            text=True,
            check=True,
            env={
                **os.environ,
                "HOME": str(root / "home"),
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
            },
        )

    def test_a_fresh_sandbox_restores_the_last_save_once(self, tmp_path: Path) -> None:
        """Round trip: one home saved by the real gaia-save comes back in a fresh sandbox."""
        old_home = tmp_path / "old" / "agents"
        for sub in ("work/p", "state/claude", "state/opencode", "config"):
            (old_home / sub).mkdir(parents=True)
        (old_home / "work/p/app.py").write_text("print(1)\n")
        (old_home / "state/claude/session.jsonl").write_text("turn-1\n")
        db = sqlite3.connect(old_home / "state/opencode/opencode.db")
        db.execute("CREATE TABLE session (id TEXT)")
        db.execute("INSERT INTO session VALUES ('ses_1')")
        db.commit()
        db.close()
        save_dir = Path(_local(AGENTS_SAVE, tmp_path))
        _executable(tmp_path / "old" / "gaia-save", _render_save(old_home, save_dir))
        shims = tmp_path / "shims"
        _host_shims(shims)
        subprocess.run(
            [str(tmp_path / "old" / "gaia-save")],
            env=_host_env(shims),
            check=True,
            capture_output=True,
        )

        first = self._run(tmp_path)
        home = Path(_local(AGENTS_HOME, tmp_path))
        (home / "work/p/app.py").write_text("print(2)\n")
        second = self._run(tmp_path)

        assert restored_from(first.stdout) == (save_dir / ".saved_at").read_text().strip()
        assert (home / "state/claude/session.jsonl").read_text() == "turn-1\n"
        restored_db = sqlite3.connect(home / "state/opencode/opencode.db")
        assert restored_db.execute("SELECT id FROM session").fetchall() == [("ses_1",)]
        assert restored_from(second.stdout) is None, "a live home is never overwritten"
        assert (home / "work/p/app.py").read_text() == "print(2)\n"

    def test_no_save_means_nothing_is_restored(self, tmp_path: Path) -> None:
        assert RESTORED_MARKER not in self._run(tmp_path).stdout

    def test_a_save_on_a_home_never_set_up_runs_no_script_and_says_so(self, tmp_path: Path) -> None:
        result = subprocess.run(
            ["bash", "-c", _local(agents_home.SAVE_COMMAND, tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == agents_home.HOME_NOT_SET_UP

    def test_a_set_up_home_saves_through_gaia_save(self, tmp_path: Path) -> None:
        self._run(tmp_path)
        save = Path(_local(SAVE_SCRIPT, tmp_path))
        _executable(save, "#!/usr/bin/env bash\necho saved\n")
        result = subprocess.run(
            ["bash", "-c", _local(agents_home.SAVE_COMMAND, tmp_path)],
            capture_output=True,
            text=True,
            check=True,
        )
        assert result.stdout.strip() == "saved"

    def test_the_profile_block_is_replaced_not_duplicated(self, tmp_path: Path) -> None:
        profile = tmp_path / "home" / ".profile"
        profile.parent.mkdir(parents=True)
        profile.write_text("export KEEP_ME=1\n")
        self._run(tmp_path)
        self._run(tmp_path)
        text = profile.read_text()
        assert "export KEEP_ME=1" in text
        assert text.count("# >>> gaia agents >>>") == 1
        assert f"CLAUDE_CONFIG_DIR={agents_home.CLAUDE_CONFIG_DIR}" in text.replace(
            str(tmp_path / "home"), HOME
        )

    def test_opencode_data_links_into_the_home_but_a_real_dir_is_left_alone(
        self, tmp_path: Path
    ) -> None:
        self._run(tmp_path)
        link = tmp_path / "home" / ".local" / "share" / "opencode"
        assert link.is_symlink()

        other = tmp_path / "other"
        other_root = other / "home" / ".local" / "share" / "opencode"
        other_root.mkdir(parents=True)
        (other_root / "auth.json").write_text("{}")
        self._run(other)
        assert not other_root.is_symlink(), "a manual login's real data dir is never clobbered"


def _render_save(home: Path, save: Path) -> str:
    """Render gaia-save with its sandbox paths moved under temp dirs."""
    return render_vendored(
        "gaia_save.sh",
        {
            "AGENTS_HOME": str(home),
            "SAVE_ARCHIVE": str(save / "home.tgz"),
            "DB_SNAPSHOT": str(home / "state/opencode/opencode.db.snapshot"),
            "SAVE_EXCLUDES": " ".join(shlex.quote(n) for n in SAVE_EXCLUDES),
            "SAVED_AT_FILE": str(save / ".saved_at"),
        },
    )


def _render_scripts(root: Path, *, save_body: str | None = None) -> tuple[Path, Path]:
    """Render gaia-save and gaia-hook into root/agents/bin; optionally stub the save."""
    home = root / "agents"
    bin_dir = home / "bin"
    save_script = bin_dir / "gaia-save"
    _executable(save_script, save_body or _render_save(home, root / "save"))
    hook = bin_dir / "gaia-hook"
    _executable(
        hook,
        render_vendored(
            "gaia_hook.sh", {"SAVE_SCRIPT": str(save_script), "SAVE_TIMEOUT_SECONDS": "30"}
        ),
    )
    return save_script, hook


def _recording_curl(root: Path, log: Path) -> Path:
    """Install a curl stand-in that logs its auth header and body, in call order."""
    shims = root / "shims"
    _executable(
        shims / "curl",
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            auth=""
            while [ $# -gt 0 ]; do
              case "$1" in -H) case "$2" in Authorization*) auth="$2";; esac; shift;; esac
              shift
            done
            printf 'POST %s %s\\n' "$auth" "$(cat)" >> {shlex.quote(str(log))}
            """
        ),
    )
    _host_shims(shims)
    return shims


@pytest.mark.unit
class TestGaiaHook:
    def _fire(
        self, root: Path, payload: str, *, save_ok: bool = True, run_env: bool = True
    ) -> tuple[int, list[str]]:
        log = root / "calls.log"
        save_body = f"#!/usr/bin/env bash\necho SAVE >> {shlex.quote(str(log))}\n" + (
            "" if save_ok else "echo 'tar: write failed' >&2\nexit 23\n"
        )
        _, hook = _render_scripts(root, save_body=save_body)
        shims = _recording_curl(root, log)
        env = {**os.environ, "PATH": f"{shims}:{os.environ['PATH']}"}
        env.pop(LAB_CALLBACK_URL_VAR, None)
        env.pop(LAB_TOKEN_VAR, None)
        if run_env:
            env |= {LAB_CALLBACK_URL_VAR: EVENTS_URL, LAB_TOKEN_VAR: "tok-1"}
        result = subprocess.run(
            [str(hook)], input=payload, env=env, capture_output=True, text=True, check=False
        )
        return result.returncode, log.read_text().splitlines() if log.exists() else []

    def test_the_save_finishes_before_the_event_is_relayed(self, tmp_path: Path) -> None:
        """The woken todo reads the saved copy, so it must be current when the event lands."""
        code, calls = self._fire(tmp_path, '{"hook_event_name":"Stop"}')
        assert code == 0
        assert calls == ["SAVE", 'POST Authorization: Bearer tok-1 {"hook_event_name":"Stop"}']

    def test_a_failed_save_is_reported_and_the_event_still_relayed(self, tmp_path: Path) -> None:
        code, calls = self._fire(tmp_path, '{"kind":"idle"}', save_ok=False)
        assert code == 0
        assert calls[0] == "SAVE"
        reported = json.loads(calls[1].split(" ", 4)[4])
        assert reported["kind"] == "save_failed"
        assert "tar: write failed" in reported["error"]
        assert calls[2] == 'POST Authorization: Bearer tok-1 {"kind":"idle"}'

    def test_without_a_run_env_it_saves_and_relays_nothing(self, tmp_path: Path) -> None:
        code, calls = self._fire(tmp_path, '{"kind":"idle"}', run_env=False)
        assert code == 0
        assert calls == ["SAVE"]

    def test_never_exits_2_even_when_everything_fails(self, tmp_path: Path) -> None:
        """A Stop hook exiting 2 makes Claude keep going instead of stopping."""
        log = tmp_path / "calls.log"
        _, hook = _render_scripts(tmp_path, save_body="#!/usr/bin/env bash\nexit 2\n")
        shims = tmp_path / "shims"
        _executable(shims / "curl", "#!/usr/bin/env bash\ncat >/dev/null\nexit 7\n")
        _host_shims(shims)
        env = {
            **os.environ,
            "PATH": f"{shims}:{os.environ['PATH']}",
            LAB_CALLBACK_URL_VAR: EVENTS_URL,
            LAB_TOKEN_VAR: "tok-1",
        }
        result = subprocess.run(
            [str(hook)], input="{}", env=env, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0
        assert not log.exists()


@pytest.mark.unit
class TestGaiaSave:
    @pytest.fixture(autouse=True)
    def _needs_sqlite(self) -> None:
        if shutil.which("sqlite3") is None:
            pytest.skip("gaia-save needs sqlite3 (in the sandbox image)")

    def _save(self, root: Path) -> Path:
        """Run the real gaia-save; return the archive unpacked into root/unpacked."""
        save_script, _ = _render_scripts(root)
        shims = root / "shims"
        _host_shims(shims)
        subprocess.run(
            [str(save_script)],
            env=_host_env(shims),
            capture_output=True,
            text=True,
            check=True,
        )
        unpacked = root / "unpacked"
        shutil.rmtree(unpacked, ignore_errors=True)
        unpacked.mkdir()
        with tarfile.open(root / "save" / "home.tgz") as archive:
            archive.extractall(unpacked, filter="data")
        return unpacked

    def _home(self, root: Path) -> Path:
        home = root / "agents"
        for sub in ("work/p", "state/opencode", "state/claude", "config"):
            (home / sub).mkdir(parents=True, exist_ok=True)
        return home

    def test_saves_work_state_and_config_but_not_rebuildable_folders(self, tmp_path: Path) -> None:
        home = self._home(tmp_path)
        (home / "work/p/app.py").write_text("print(1)\n")
        (home / "work/p/node_modules/x").mkdir(parents=True)
        (home / "work/p/node_modules/x/index.js").write_text("x")
        (home / "work/p/.venv/bin").mkdir(parents=True)
        (home / "state/claude/session.jsonl").write_text("turn\n")

        saved = self._save(tmp_path)

        assert (saved / "work/p/app.py").read_text() == "print(1)\n"
        assert (saved / "state/claude/session.jsonl").is_file()
        assert not (saved / "work/p/node_modules").exists()
        assert not (saved / "work/p/.venv").exists()
        assert (tmp_path / "save/.saved_at").read_text().strip()

    def test_a_file_deleted_locally_is_gone_from_the_next_save(self, tmp_path: Path) -> None:
        home = self._home(tmp_path)
        (home / "work/p/old.txt").write_text("old")
        self._save(tmp_path)
        (home / "work/p/old.txt").unlink()
        assert not (self._save(tmp_path) / "work/p/old.txt").exists()

    def test_opencode_database_is_saved_as_a_consistent_snapshot(self, tmp_path: Path) -> None:
        home = self._home(tmp_path)
        db = sqlite3.connect(home / "state/opencode/opencode.db")
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE session (id TEXT)")
        db.execute("INSERT INTO session VALUES ('ses_1')")
        db.commit()  # left open: the live CLI holds it with WAL pages unmerged

        saved = self._save(tmp_path)
        db.close()

        opencode = saved / "state/opencode"
        assert sorted(p.name for p in opencode.iterdir()) == ["opencode.db.snapshot"]
        snapshot = sqlite3.connect(opencode / "opencode.db.snapshot")
        assert snapshot.execute("SELECT id FROM session").fetchall() == [("ses_1",)]


@pytest.mark.unit
class TestNotifyPlugin:
    @pytest.fixture(autouse=True)
    def _needs_node(self) -> None:
        if shutil.which("node") is None:
            pytest.skip("node is not installed; the plugin is exercised live instead")

    def _run_plugin(
        self, tmp_path: Path, events: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        log = tmp_path / "piped.log"
        hook = tmp_path / "gaia-hook"
        _executable(
            hook,
            f"#!/usr/bin/env bash\ncat >> {shlex.quote(str(log))}\necho >> {shlex.quote(str(log))}\n",
        )
        plugin = tmp_path / "gaia_notify.mjs"
        plugin.write_text(
            render_vendored(
                "opencode_notify_plugin.js",
                {"GAIA_HOOK": str(hook), "HOOK_TIMEOUT_SECONDS": "10"},
            )
        )
        driver = tmp_path / "drive.mjs"
        driver.write_text(
            f"import plugin from {json.dumps(str(plugin))};\n"
            "const hooks = await plugin.server();\n"
            f"for (const event of {json.dumps(events)}) await hooks.event({{ event }});\n"
        )
        subprocess.run(["node", str(driver)], check=True, capture_output=True, text=True)
        return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []

    def test_a_turn_end_is_piped_to_gaia_hook_once(self, tmp_path: Path) -> None:
        """1.18 fires session.idle twice per turn end; each relay runs the todo, so once."""
        idle = {"type": "session.idle", "properties": {"sessionID": "ses_1"}}
        piped = self._run_plugin(tmp_path, [idle, idle])
        assert piped == [{"kind": "idle", "raw": idle}]

    def test_streaming_chatter_is_never_piped(self, tmp_path: Path) -> None:
        chatter = {"type": "message.part.updated", "properties": {"sessionID": "ses_1"}}
        assert self._run_plugin(tmp_path, [chatter]) == []


@pytest.mark.unit
class TestLabHooksToken:
    def test_hooks_token_carries_an_empty_tool_scope(self) -> None:
        with patch.object(execute_token.settings, "SANDBOX_EXECUTE_TOKEN_SECRET", SECRET):
            token = mint_lab_hooks_token("u1", "lab-1")
            claims = execute_token.verify_execute_token(token)

        assert claims.user_id == "u1"
        assert claims.run_id == "lab-1"
        assert claims.scoped_tool_names == []

    def test_unconfigured_events_url_fails_loud(self) -> None:
        with patch.object(sandbox_setup.settings, "SANDBOX_LAB_EVENTS_CALLBACK_URL", None):
            with pytest.raises(AppError) as err:
                sandbox_setup.lab_events_url()
        assert err.value.status_code == 503
