#!/bin/bash
# Verify the sandbox's credential-isolation defenses are intact.
#
# Run inside an acquired sandbox AS THE UNPRIVILEGED USER after every E2B
# template rebuild or `E2B_TEMPLATE_ID` rotation. Each numbered check is
# one wall in the defense; all must pass for Finding 3 to stay closed.
#
# Delivery: push-on-demand. The script is NOT baked into the template
# (keeps the sandbox surface minimal). Upload via `sbx.files.write`, run,
# then delete:
#
#   await sbx.files.write("/tmp/verify.sh", open("verify_sandbox_hardening.sh").read())
#   await sbx.commands.run("chmod +x /tmp/verify.sh && /tmp/verify.sh")
#   await sbx.files.remove("/tmp/verify.sh")
#
# Exit codes:
#   0  all walls hold
#   1  at least one wall is broken — DO NOT promote the template

set -u

fail=0
pass() { printf '  \033[32mPASS\033[0m %s\n' "$1"; }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; }
crit() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

echo
echo "===> Sandbox hardening verification"
echo

# ---------------------------------------------------------------------------
# Wall 1: sudo strip
# ---------------------------------------------------------------------------
echo "[1/7] Unprivileged user has no sudo"
if ! command -v sudo >/dev/null 2>&1; then
    pass "sudo binary is absent (purged from template)"
else
    sudo_out=$(sudo -n true 2>&1 || true)
    if echo "$sudo_out" | grep -qiE "password is required|not in the sudoers|not allowed"; then
        pass "sudo binary present but denied"
    else
        crit "sudo unexpectedly succeeded or returned: $sudo_out"
    fi
fi

# ---------------------------------------------------------------------------
# Wall 2: hidepid hides root processes
# ---------------------------------------------------------------------------
echo "[2/7] hidepid hides root-owned processes from /proc listings"
jfs_pid=$(pgrep -x juicefs 2>/dev/null | head -1 || true)
if [ -z "$jfs_pid" ]; then
    pass "juicefs PID not visible to unprivileged user (hidepid working)"
else
    # PID is visible — hidepid may not be applied. Continue checks but flag.
    warn "juicefs PID visible ($jfs_pid); hidepid may not be active. Continuing..."
fi

# ---------------------------------------------------------------------------
# Wall 3: PR_SET_DUMPABLE on juicefs daemon
# ---------------------------------------------------------------------------
echo "[3/7] juicefs /proc/<pid>/cmdline is not readable by unprivileged user"
if [ -n "${jfs_pid:-}" ]; then
    cmd_out=$(cat "/proc/$jfs_pid/cmdline" 2>&1 || true)
    if [ -z "$cmd_out" ] || echo "$cmd_out" | grep -qi "permission denied"; then
        pass "cmdline blocked"
    else
        crit "cmdline leaked: $cmd_out"
    fi
else
    # If hidepid worked we can't see the PID at all — counts as pass.
    pass "PID unfindable (no cmdline path to test)"
fi

echo "[4/7] juicefs /proc/<pid>/environ is not readable by unprivileged user"
if [ -n "${jfs_pid:-}" ]; then
    env_out=$(cat "/proc/$jfs_pid/environ" 2>&1 || true)
    if [ -z "$env_out" ] || echo "$env_out" | grep -qi "permission denied"; then
        pass "environ blocked"
    else
        crit "environ leaked: $(echo "$env_out" | tr '\0' '\n' | grep -E 'JFS_|R2_|META_' | head -3)"
    fi
else
    pass "PID unfindable (no environ path to test)"
fi

# ---------------------------------------------------------------------------
# Wall 4: no credentials in unprivileged shell's own env
# ---------------------------------------------------------------------------
echo "[5/7] User shell environ contains no JuiceFS / R2 credentials"
leaked=$(env | grep -E '^(JFS_|R2_|META_PASSWORD=|AWS_ACCESS|AWS_SECRET)' || true)
if [ -z "$leaked" ]; then
    pass "user environ is clean"
else
    crit "creds present in user shell:"
    echo "$leaked" | sed 's/^/    /'
fi

# ---------------------------------------------------------------------------
# Functional regression checks — make sure agent capability is preserved
# ---------------------------------------------------------------------------
echo "[6/7] /workspace mount is healthy (JuiceFS or ephemeral)"
if mountpoint -q /workspace; then
    pass "/workspace is a mount"
elif [ -d /workspace ] && [ -w /workspace ]; then
    warn "/workspace is ephemeral (not a JuiceFS mount) — fine for dev, durability lost"
else
    crit "/workspace missing or not writable"
fi

echo "[7/7] Unprivileged user can still do its job"
ok_python=0
ok_pip=0
python3 -c "print('hi')" >/dev/null 2>&1 && ok_python=1
pip install --user --dry-run pyyaml >/dev/null 2>&1 && ok_pip=1
if [ "$ok_python" = 1 ] && [ "$ok_pip" = 1 ]; then
    pass "python + pip --user work without root"
else
    crit "agent capability regression: python=$ok_python pip=$ok_pip"
fi

echo
if [ "$fail" = 0 ]; then
    printf '\033[32m===> ALL CHECKS PASSED\033[0m\n'
    exit 0
else
    printf '\033[31m===> FAILED — DO NOT PROMOTE THIS TEMPLATE\033[0m\n'
    exit 1
fi
