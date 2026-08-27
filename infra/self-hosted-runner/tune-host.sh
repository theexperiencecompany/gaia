#!/usr/bin/env bash
# tune-host.sh — put gaia-home-server into a CI-appropriate performance profile.
#
# Separate from setup.sh because this changes machine-wide behaviour rather
# than just installing runner instances: it should be a deliberate, reviewable
# step, and it is safe to skip entirely.
#
# What it changes and why:
#   * CPU governor powersave -> performance. CI is a burst workload of short,
#     latency-sensitive compile and test steps. `powersave` ramps clocks up
#     reactively, so the ramp lands after a short step has already finished and
#     the box runs much of the job below its rated clock.
#   * Installs a systemd unit so the governor survives a reboot (the sysfs
#     setting does not).
#
# All root work happens in ONE sudo invocation. Doing it as a series of `sudo`
# calls means re-authenticating for each one over a non-interactive session
# (sudo's credential cache is per-tty, and there is no tty), which is why this
# is written as a single payload rather than sprinkled sudo lines.
#
# Idempotent. Run:  bash infra/self-hosted-runner/tune-host.sh
#         Revert:   bash infra/self-hosted-runner/tune-host.sh --revert
#
# Non-interactive (password on stdin):
#   printf '%s\n' "$PW" | bash infra/self-hosted-runner/tune-host.sh
set -euo pipefail

MODE="performance"
[[ "${1:-}" == "--revert" ]] && MODE="powersave"

echo "[tune] Host: $(hostname) — $(nproc) vCPUs, $(free -h | awk '/^Mem:/{print $2}') RAM"

if [[ ! -d /sys/devices/system/cpu/cpu0/cpufreq ]]; then
  echo "[tune] No cpufreq sysfs interface — nothing to tune."
  exit 0
fi

CURRENT="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
AVAILABLE="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors 2>/dev/null || echo '')"
echo "[tune] Governor: current=$CURRENT available=${AVAILABLE:-unknown} target=$MODE"

if [[ -n "$AVAILABLE" && "$AVAILABLE" != *"$MODE"* ]]; then
  echo "::warning::governor '$MODE' unavailable on this kernel — leaving $CURRENT in place"
  exit 0
fi

PAYLOAD="$(mktemp)"
trap 'rm -f "$PAYLOAD"' EXIT
cat > "$PAYLOAD" <<PAYLOAD_EOF
set -euo pipefail
for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
  echo "$MODE" > "\$g"
done
if [[ "$MODE" == "performance" ]]; then
  cat > /etc/systemd/system/cpu-governor-performance.service <<'UNIT'
[Unit]
Description=Set CPU governor to performance (CI host)
After=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "\$g"; done'

[Install]
WantedBy=multi-user.target
UNIT
  systemctl daemon-reload
  systemctl enable cpu-governor-performance.service >/dev/null 2>&1 || true
else
  systemctl disable --now cpu-governor-performance.service >/dev/null 2>&1 || true
  rm -f /etc/systemd/system/cpu-governor-performance.service
  systemctl daemon-reload
fi
PAYLOAD_EOF

# -S reads the password from stdin when there is no tty, and is harmless when
# there is one (sudo still prompts normally).
if sudo -n true 2>/dev/null; then
  sudo bash "$PAYLOAD"
else
  sudo -S -p "" bash "$PAYLOAD"
fi

echo "[tune] Governor now: $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor) on all $(nproc) CPUs"
[[ "$MODE" == "performance" ]] && echo "[tune] Persisted via cpu-governor-performance.service (survives reboot)"
echo "[tune] /dev/shm: $(df -h /dev/shm | awk 'NR==2{print $4" free of "$2}')  (mutation workdirs stage here)"
echo "[tune] Done."
