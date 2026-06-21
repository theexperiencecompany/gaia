"""Desktop app constants.

Release distribution for the marketing download page — see
``app.services.desktop.releases``.
"""

# GAIA's monorepo. Desktop builds are tagged ``desktop-<version>`` and share the
# repo's single GitHub Releases feed with every other app.
GAIA_GITHUB_REPO = "theexperiencecompany/gaia"
DESKTOP_RELEASE_TAG_PREFIX = "desktop-"

# GitHub's max page size. Desktop releases recur often enough that the newest one
# always lands within the first page even interleaved with the far more frequent
# web/api/cli/bots/mobile releases — a smaller page silently hid it and forced
# every download button to fall back to the raw releases list.
DESKTOP_RELEASES_PAGE_SIZE = 100

# Upper bound on the GitHub releases fetch.
GITHUB_RELEASES_TIMEOUT_SECONDS = 15.0
