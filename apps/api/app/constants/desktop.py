"""Desktop app constants.

Release distribution for the marketing download page — see
app.services.desktop.releases.
"""

# GAIA's monorepo. Desktop builds are tagged ``desktop-<version>`` and share the
# repo's single GitHub Releases feed with every other app.
GAIA_GITHUB_REPO = "theexperiencecompany/gaia"
DESKTOP_RELEASE_TAG_PREFIX = "desktop-"

# GitHub's max page size: keeps the newest desktop release within the first
# page even interleaved with far more frequent web/api/cli/bots/mobile releases.
DESKTOP_RELEASES_PAGE_SIZE = 100

# Upper bound on the GitHub releases fetch.
GITHUB_RELEASES_TIMEOUT_SECONDS = 15.0
