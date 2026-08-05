"""
Onboarding Constants.

Shared constants for the onboarding intelligence pipeline and its deferred ARQ
jobs — used by the job-lifecycle helpers (`intelligence_job`) and the pipeline
itself (`intelligence_service`).
"""

from app.config.oauth_config import OAUTH_INTEGRATIONS

# ARQ task names — must match the registered worker task functions.
INTELLIGENCE_TASK = "process_onboarding_intelligence_task"
WORKFLOWS_TASK = "process_onboarding_workflows_task"

# Dotted Mongo paths storing each job slot's active ARQ job id on the user doc,
# so a re-enqueue or reset can abort the in-flight job.
INTELLIGENCE_JOB_FIELD = "onboarding.intelligence_job_id"
WORKFLOWS_JOB_FIELD = "onboarding.workflows_job_id"

# Fallback first assistant message.

# Start triage once this many emails are buffered, without waiting for the full fetch.
TRIAGE_EARLY_THRESHOLD = 100

# Split-mode early phase: how long to wait for the integration-selection marker,
# and how often to poll for it, before proceeding with persisted data.
EARLY_PHASE_WAIT_TIMEOUT_S = 300
EARLY_PHASE_POLL_INTERVAL_S = 2.0

# Sentinel substituted into prompts when profession/focus is unset.
NOT_SPECIFIED = "not specified"

# Known integration ids -> display name, used to validate request-backed
# `selected_integrations` before they reach prompts or workflow generation.
OAUTH_INTEGRATION_NAME_BY_ID = {i.id: i.name for i in OAUTH_INTEGRATIONS}
