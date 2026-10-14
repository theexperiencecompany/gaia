"""`packages/cli/install.sh` on a fresh server: no Node yet is the expected path, not a warning.

Hermetic: PATH holds only the coreutils the script needs plus a curl shim that
serves a fake nvm, whose `nvm install` drops node/npm shims and whose
`npm install -g` drops a gaia shim. Real nvm, Node and npm are never touched.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
INSTALL_SH = REPO_ROOT / "packages" / "cli" / "install.sh"

HOST_TOOLS = ("sh", "bash", "uname", "mkdir", "cat", "chmod")

# What `curl …/nvm-sh/nvm/…/install.sh` returns: an nvm whose install puts
# node and npm on PATH, and an npm whose global install puts gaia there.
FAKE_NVM_INSTALLER = r"""
mkdir -p "$HOME/.nvm/bin"
cat > "$HOME/.nvm/nvm.sh" <<'NVM'
nvm() {
  printf '#!/bin/sh\necho v22.0.0\n' > "$NVM_DIR/bin/node"
  printf '#!/bin/sh\nprintf "#!/bin/sh\\n" > "$NVM_DIR/bin/gaia"; chmod +x "$NVM_DIR/bin/gaia"\n' > "$NVM_DIR/bin/npm"
  chmod +x "$NVM_DIR/bin/node" "$NVM_DIR/bin/npm"
  PATH="$NVM_DIR/bin:$PATH"
}
NVM
"""

CURL_SHIM = f"""#!/bin/sh
cat <<'INSTALLER'
{FAKE_NVM_INSTALLER}
INSTALLER
"""


@pytest.fixture
def fresh_server(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in HOST_TOOLS:
        real = shutil.which(tool)
        assert real, f"{tool} is needed to run install.sh"
        (bin_dir / tool).symlink_to(real)
    curl = bin_dir / "curl"
    curl.write_text(CURL_SHIM)
    curl.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    return {"PATH": str(bin_dir), "HOME": str(home), "TERM": os.environ.get("TERM", "dumb")}


def test_no_node_yet_is_info_and_says_nvm_comes_next(fresh_server: dict[str, str]) -> None:
    result = subprocess.run(
        ["sh", str(INSTALL_SH)], capture_output=True, check=False, text=True, env=fresh_server
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No supported package manager" not in result.stdout
    assert (
        "[info]\033[0m No Node.js package manager yet (npm, pnpm, or bun), "
        "so installing Node.js via nvm..."
    ) in result.stdout
    assert "Node.js v22.0.0 installed successfully" in result.stdout
    assert "[warn]\033[0m Node.js was installed with nvm" in result.stdout
