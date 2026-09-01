"""
Gmail personalization pipeline constants.

Shared between the job-lifecycle helpers (`intelligence_job`) and the pipeline
itself (`intelligence_service`), which run when a user connects Gmail.
"""

# ARQ task name — must match the registered worker task function.
INTELLIGENCE_TASK = "process_onboarding_intelligence_task"

# Dotted Mongo path storing the active ARQ job id on the user doc, so a
# re-enqueue can abort the in-flight job.
INTELLIGENCE_JOB_FIELD = "onboarding.intelligence_job_id"

# Key inside the `onboarding` subdocument stamped once the pipeline has run for
# a user. Its presence is what makes a Gmail reconnect a no-op.
GMAIL_PERSONALIZATION_MARKER = "gmail_personalization_at"

# Holo-card field written by the pre-relocation onboarding pipeline. Users who
# completed that flow carry it but no marker, so it stands in as the marker for
# them and keeps the pipeline from re-running on their next Gmail reconnect.
LEGACY_PERSONALIZATION_MARKER = "house"

# Key inside the `onboarding` subdocument holding the seeded holo-card
# conversation, so a reset can tear it down again.
HOLO_CONVERSATION_ID_FIELD = "holo_conversation_id"

# Start triage once this many emails are buffered, without waiting for the full fetch.
TRIAGE_EARLY_THRESHOLD = 100
