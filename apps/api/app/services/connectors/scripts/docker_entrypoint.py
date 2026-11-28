"""A docker connector call's entrypoint: write the call's files, set its env, exec its argv.

The payload arrives in one env var the docker CLI forwards by name, so neither
the secret nor the credential files ever appear in a host process's argv.
"""

from collections.abc import Iterable, Mapping
import json
import os
from pathlib import Path
import sys
from typing import TypedDict

PAYLOAD_ENV = "GAIA_CONNECTOR_PAYLOAD"
FILE_MODE = 0o600
DIR_MODE = 0o700
EXIT_NOT_FOUND = 127
EXIT_USAGE = 2


class PayloadFile(TypedDict):
    path: str
    content: str


class Payload(TypedDict):
    env: dict[str, str]
    files: list[PayloadFile]


def encode_payload(env: Mapping[str, str], files: Iterable[PayloadFile]) -> str:
    """Encode what one call needs for the host to hand over in PAYLOAD_ENV."""
    return json.dumps(Payload(env=dict(env), files=list(files)))


def apply_payload(raw: str) -> None:
    """Write the payload's files and put its env into this process's environment."""
    payload: Payload = json.loads(raw)
    for entry in payload["files"]:
        _write_private(entry)
    os.environ.update(payload["env"])


def _write_private(entry: PayloadFile) -> None:
    path = Path(entry["path"])
    path.parent.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, FILE_MODE)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(entry["content"])


def main(argv: list[str]) -> int:
    """Apply the payload, close stdin, and replace this process with argv."""
    if not argv:
        print("docker_entrypoint.py: no command to run", file=sys.stderr)
        return EXIT_USAGE
    apply_payload(os.environ.pop(PAYLOAD_ENV))
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, sys.stdin.fileno())
    os.close(devnull)
    try:
        os.execvp(argv[0], argv)
    except FileNotFoundError:
        print(f"{argv[0]}: command not found", file=sys.stderr)
        return EXIT_NOT_FOUND


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
