"""Constants for OpenUI artifacts: create_artifact's generation, validation and streaming."""

from pathlib import Path

# The Node validator bundle (tools/artifact-validate), relative to the repo root, which is
# /app in the API image and the checkout root natively.
REPO_ROOT = Path(__file__).resolve().parents[4]
ARTIFACT_VALIDATOR_BUNDLE = REPO_ROOT / "tools" / "artifact-validate" / "dist" / "validate.cjs"
ARTIFACT_VALIDATOR_TIMEOUT_SECONDS = 20

# Generated per-kind system prompts (scripts/openui/generate-artifact-prompt.ts).
ARTIFACT_PROMPTS_DIR = REPO_ROOT / "apps" / "api" / "app" / "agents" / "prompts" / "artifacts"

# One generation, repair included, gives up after this long and the tool reports a timeout.
ARTIFACT_GENERATION_TIMEOUT_SECONDS = 120
ARTIFACT_MAX_OUTPUT_TOKENS = 8_000
ARTIFACT_MAX_REPAIRS = 1

# Model deltas are token-sized; batch them so one artifact is tens of SSE frames, not hundreds.
ARTIFACT_DELTA_FLUSH_SECONDS = 0.12
ARTIFACT_DELTA_FLUSH_CHARS = 400

ARTIFACT_REPAIR_INSTRUCTION = "Return only the corrected program, starting with root ="

# Live-only stream frame carrying a program chunk; the card accumulates it.
ARTIFACT_DELTA_EVENT = "artifact_delta"
# The persisted chat card entry (a tool_fields key).
ARTIFACT_DONE_EVENT = "artifact_done"

# PDF export: the web page that prints an artifact, the marker it sets once rendered, and
# how long a printed (artifact id, version) stays cached.
ARTIFACT_PRINT_URL = "{frontend}/l/{slug}?print=1"
ARTIFACT_READY_SELECTOR = "[data-artifact-ready]"
ARTIFACT_PDF_CACHE_KEY = "artifact_pdf:{artifact_id}:{version}"
ARTIFACT_PDF_CACHE_TTL_SECONDS = 7 * 24 * 3600
