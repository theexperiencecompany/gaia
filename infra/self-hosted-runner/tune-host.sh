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
#   * zram swap + the kernel's recommended VM knobs for it. The box had no
#     zram, an 8 GB disk swap file at priority -1 and vm.swappiness=60 — stock
#     desktop settings. Under a memory spike (observed: 16 pytest workers at
#     2.5 GB each) that means paging to NVMe with a load average of 42 and
#     every core busy doing nothing. zram compresses cold pages in RAM
#     (zstd, typically 3-4x) at memory speed; the disk file stays as the last
#     resort behind it. Knob values are the ones the kernel zram docs
#     recommend (Documentation/admin-guide/blockdev/zram.rst), not folklore:
#     swappiness 180 (swapping to zram is cheaper than dropping page cache),
#     page-cluster 0 (no readahead — zram has no seek cost), and the
#     watermark settings that make the kernel start compressing early rather
#     than stalling under pressure.
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

ZRAM_PCT="${ZRAM_PCT:-50}"   # zram size as % of RAM; 50% of 46 GiB ≈ 23 GiB uncompressed capacity
cat >> "$PAYLOAD" <<PAYLOAD_EOF
# ---- zram + VM tuning ----
if [[ "$MODE" == "performance" ]]; then
  if ! dpkg -s systemd-zram-generator >/dev/null 2>&1; then
    apt-get install -y -qq systemd-zram-generator >/dev/null 2>&1 || echo "WARN: could not install systemd-zram-generator"
  fi
  cat > /etc/systemd/zram-generator.conf <<'ZCONF'
# CI host: compressed swap in RAM ahead of the disk swap file.
[zram0]
zram-size = ram * ${ZRAM_PCT} / 100
compression-algorithm = zstd
swap-priority = 100
ZCONF
  cat > /etc/sysctl.d/99-gaia-ci-vm.conf <<'SCONF'
# Kernel zram documentation recommendations (blockdev/zram.rst).
vm.swappiness = 180
vm.page-cluster = 0
vm.watermark_boost_factor = 0
vm.watermark_scale_factor = 125
# Large, bursty writers (docker layers, uv/pnpm extraction): let more dirty
# pages accumulate before forcing synchronous writeback on 46 GiB.
vm.dirty_background_ratio = 5
vm.dirty_ratio = 20
SCONF
  sysctl -q --system >/dev/null
  systemctl daemon-reload
  systemctl restart systemd-zram-setup@zram0.service 2>/dev/null || true
  # Drain stale pages out of the disk swap file so it starts empty behind zram.
  if grep -q '^/swap.img' /proc/swaps; then
    avail_kb=\$(awk '/MemAvailable/{print \$2}' /proc/meminfo); used_kb=\$(awk '/^\/swap.img/{print \$4}' /proc/swaps)
    if (( avail_kb > used_kb * 2 )); then swapoff /swap.img && swapon -p -1 /swap.img; fi
  fi
else
  rm -f /etc/systemd/zram-generator.conf /etc/sysctl.d/99-gaia-ci-vm.conf
  systemctl daemon-reload; swapoff /dev/zram0 2>/dev/null || true
  sysctl -q -w vm.swappiness=60 vm.page-cluster=3 vm.watermark_boost_factor=15000 vm.watermark_scale_factor=10 vm.dirty_background_ratio=10 vm.dirty_ratio=20 >/dev/null
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
echo "[tune] swap:"; awk 'NR>1{printf "        %-14s %6.1f GiB  prio %s\n", $1, $3/1048576, $5}' /proc/swaps
[[ -e /sys/block/zram0/comp_algorithm ]] && echo "[tune] zram0: $(cat /sys/block/zram0/comp_algorithm | grep -o '\[[a-z0-9]*\]') $(numfmt --to=iec < /sys/block/zram0/disksize)"
echo "[tune] vm: swappiness=$(sysctl -n vm.swappiness) page-cluster=$(sysctl -n vm.page-cluster) watermark_scale=$(sysctl -n vm.watermark_scale_factor)"
echo "[tune] Done."
