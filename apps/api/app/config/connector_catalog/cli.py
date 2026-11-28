"""Catalog connectors that run a provider's own CLI, pinned per CPU and checksummed."""

from app.config.connector_catalog.row import CatalogRow

_GH_VERSION = "2.106.0"
# From the release's gh_2.106.0_checksums.txt.
_GH_SHA256 = {
    "amd64": "a476449fa9625413c54a3734eded62e9e480e49f421ff08e7f3b3879c059a033",
    "arm64": "5e8a0c51e1a8345f36bd0b8bb88604b6a5388df16f3ab3e3b9b6d794fa223a67",
}

CLI_CONNECTORS: list[CatalogRow] = [
    CatalogRow(
        id="github-cli",
        name="GitHub CLI",
        description=(
            "GitHub's own command line tool. GAIA can read repositories, issues, pull "
            "requests, Actions runs and releases, and call any GitHub API endpoint."
        ),
        spec={
            "kind": "cli",
            "provider_domain": "github.com",
            "capability": "Read and manage your GitHub repositories, pull requests and Actions",
            "command": "gh",
            "install": [
                {
                    "manager": "binary",
                    "name": "gh",
                    "version": _GH_VERSION,
                    "arch": arch,
                    "url": (
                        f"https://github.com/cli/cli/releases/download/v{_GH_VERSION}/"
                        f"gh_{_GH_VERSION}_linux_{arch}.tar.gz"
                    ),
                    "sha256": sha256,
                    "archive_member": f"gh_{_GH_VERSION}_linux_{arch}/bin/gh",
                }
                for arch, sha256 in _GH_SHA256.items()
            ],
            "credential": {
                "env": ["GH_TOKEN"],
                "label": "personal access token",
                "token_url": "https://github.com/settings/tokens",  # nosec B105 -- a page URL, not a key
            },
            "usage": {
                "json_flag": "--json",
                "guidance": (
                    "Pass --repo OWNER/REPO on every repo-scoped command: there is no checkout. "
                    "list/view commands take --json FIELDS (run with --json alone to see the "
                    'fields). `api` reaches any REST path, e.g. ["api", "repos/OWNER/REPO"].'
                ),
            },
            "risk": {
                "read_commands": [
                    "api",
                    "auth status",
                    "search",
                    "status",
                    "repo list",
                    "repo view",
                    "issue list",
                    "issue view",
                    "issue status",
                    "pr list",
                    "pr view",
                    "pr diff",
                    "pr checks",
                    "pr status",
                    "run list",
                    "run view",
                    "workflow list",
                    "workflow view",
                    "release list",
                    "release view",
                    "gist list",
                    "gist view",
                    "label list",
                    "org list",
                    "cache list",
                    "variable list",
                    "secret list",
                ],
                "write_flags": ["-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"],
            },
            "allowed_hosts": ["api.github.com", "github.com", "uploads.github.com"],
            "verify": {"args": ["api", "user"], "identity": {"json_path": "login"}},
        },
    ),
]
