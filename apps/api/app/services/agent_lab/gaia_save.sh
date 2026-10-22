#!/usr/bin/env bash
# gaia-save: pack the coding agents' home (local disk) into one archive on JuiceFS.
#
# Rendered per sandbox by agents_home.py. One archive, not a file-by-file copy:
# each JuiceFS file write costs several metadata round trips (~6s per file
# measured with rsync), so a save writes one file whatever changed. OpenCode's
# live SQLite database ships as a .backup snapshot (a raw copy can be torn
# mid-write). One save at a time per sandbox (flock).
set -euo pipefail

home="{{AGENTS_HOME}}"
archive="{{SAVE_ARCHIVE}}"
db="$home/state/opencode/opencode.db"
staged="$home/.home.tgz"

exec 9>"$home/.save.lock"
flock 9

if [ -f "$db" ]; then
    sqlite3 "$db" ".backup '{{DB_SNAPSHOT}}'"
fi

excludes=({{SAVE_EXCLUDES}})
args=()
for name in "${excludes[@]}"; do
    args+=(--exclude "$name")
done

# Exit 1 is "a file changed while being read": a live agent's transcript, fine to save.
rc=0
tar -czf "$staged" "${args[@]}" --exclude 'opencode.db' --exclude 'opencode.db-*' \
    -C "$home" work state config || rc=$?
[ "$rc" -le 1 ]

mkdir -p "$(dirname "$archive")"
cp "$staged" "$archive.tmp"
mv -f "$archive.tmp" "$archive"
date -u +%Y-%m-%dT%H:%M:%SZ > "{{SAVED_AT_FILE}}"
