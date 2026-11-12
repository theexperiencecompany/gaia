"""Constants for OpenUI artifacts: create_artifact's generation, validation and streaming."""

from pathlib import Path

# The Node validator bundle (tools/artifact-validate), relative to the repo root, which is
# /app in the API image and the checkout root natively.
REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_VALIDATOR_BUNDLE = REPO_ROOT / "tools" / "artifact-validate" / "dist" / "validate.cjs"
ARTIFACT_VALIDATOR_TIMEOUT_SECONDS = 20

# Generated per-kind system prompts (scripts/openui/generate-artifact-prompt.ts), found from the
# app package so the mutation lane's relocated copy of app/ still reads them.
ARTIFACT_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "agents" / "prompts" / "artifacts"

# One generation, repair included, gives up after this long and the tool reports a timeout.
ARTIFACT_GENERATION_TIMEOUT_SECONDS = 120
ARTIFACT_MAX_OUTPUT_TOKENS = 8_000
ARTIFACT_MAX_REPAIRS = 1
# Per-user abuse cap on create_artifact a day (rate limit feature artifact_creation).
ARTIFACT_CREATION_DAILY_CAP = 200
# The daily cap every day of the longest month: the cap is per day, never a monthly quota.
ARTIFACT_CREATION_MONTHLY_CAP = 31 * ARTIFACT_CREATION_DAILY_CAP

# Model deltas are token-sized; batch them so one artifact is tens of SSE frames, not hundreds.
ARTIFACT_DELTA_FLUSH_SECONDS = 0.12
ARTIFACT_DELTA_FLUSH_CHARS = 400

ARTIFACT_REPAIR_INSTRUCTION = "Return only the corrected program, starting with root ="

# Live-only stream frame carrying a program chunk; the card accumulates it.
ARTIFACT_DELTA_EVENT = "artifact_delta"
# The persisted chat card entry (a tool_fields key).
ARTIFACT_DONE_EVENT = "artifact_done"

# PDF export: the web page that prints a program handed to it, the marker it sets once
# rendered, and
# how long a printed (artifact id, version) stays cached.
ARTIFACT_PRINT_URL = "{frontend}/artifact-print"
# The window global the print page reads its program from (ArtifactPrintView.tsx).
ARTIFACT_PRINT_PROGRAM_GLOBAL = "__GAIA_ARTIFACT_PROGRAM__"
ARTIFACT_READY_SELECTOR = "[data-artifact-ready]"
ARTIFACT_PDF_CACHE_KEY = "artifact_pdf:{artifact_id}:{version}"
ARTIFACT_PDF_CACHE_TTL_SECONDS = 7 * 24 * 3600

#: Chromium renders running at once on one API process; the rest wait their turn.
PDF_RENDER_MAX_CONCURRENT = 2
#: Renders allowed to wait for a turn; past it a request is refused with 429.
PDF_RENDER_MAX_WAITING = 6
#: The public short link's PDF route: /api/v1/l/{slug}/pdf.
PUBLIC_PDF_PATH_PATTERN = r"/api/v1/l/[^/]+/pdf"
