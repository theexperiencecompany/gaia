#!/usr/bin/env bash
# tune-host.sh — put gaia-home-server into a CI-appropriate performance profile.
#
# Separate from setup.sh because this changes machine-wide behaviour (power
# and memory policy) rather than just installing runner instances: it should
# be a deliberate, reviewable step, and it is safe to skip entirely.
#
# What it changes and why:
#   * CPU governor powersave -> performance. CI is a burst workload of short,
#     latency-sensitive compile and test steps. `powersave` ramps clocks up
#     reactively, so the ramp lands after a short step has already finished
#     and the box runs the whole job below its rated clock.
#   * /dev/shm sizing. The mutation lane stages its workdirs on tmpfs
#     (scripts/test/mutation.sh); the default half-of-RAM is already ample
#     here, so this only reports it.
#
# Idempotent. Run:  bash infra/self-hosted-runner/tune-host.sh
#         Revert:  sudo bash infra/self-hosted-runner/tune-host.sh --revert
set -euo pipefail

MODE="performance"
if [[ "${1:-}" == "--revert" ]]; then
  MODE="powersave"
fi

echo "[tune] Host: $(hostname) — $(nproc) vCPUs, $(free -h | awk '/^Mem:/{print $2}') RAM"

if [[ ! -d /sys/devices/system/cpu/cpu0/cpufreq ]]; then
  echo "[tune] No cpufreq sysfs interface — skipping governor change."
else
  CURRENT="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor)"
  AVAILABLE="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors 2>/dev/null || echo '')"
  echo "[tune] Governor: current=$CURRENT available=${AVAILABLE:-unknown} target=$MODE"

  if [[ -n "$AVAILABLE" && "$AVAILABLE" != *"$MODE"* ]]; then
    echo "::warning::governor '$MODE' not available on this kernel — leaving $CURRENT in place"
  elif [[ "$CURRENT" == "$MODE" ]]; then
    echo "[tune] Already $MODE — nothing to do."
  else
    for gov in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
      echo "$MODE" | sudo tee "$gov" > /dev/null
    done
    echo "[tune] Governor set to $MODE on all $(nproc) CPUs."
  fi

  # sysfs governor settings reset on reboot; a tiny unit re-applies them.
  if [[ "$MODE" == "performance" ]]; then
    sudo tee /etc/systemd/system/cpu-governor-performance.service > /dev/null <<'UNIT'
[Unit]
Description=Set CPU governor to performance (CI host)
After=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/bin/bash -c 'for g in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do echo performance > "$g"; done'

[Install]
WantedBy=multi-user.target
UNIT
    sudo systemctl daemon-reload
    sudo systemctl enable --now cpu-governor-performance.service > /dev/null 2>&1 || true
    echo "[tune] Persisted via cpu-governor-performance.service (survives reboot)."
  else
    sudo systemctl disable --now cpu-governor-performance.service > /dev/null 2>&1 || true
    sudo rm -f /etc/systemd/system/cpu-governor-performance.service
    sudo systemctl daemon-reload
    echo "[tune] Removed the persistence unit."
  fi
fi

echo "[tune] /dev/shm: $(df -h /dev/shm | awk 'NR==2{print $4" free of "$2}')  (mutation workdirs stage here)"
echo "[tune] Done."
