/** The general-assistant target value (matches backend EXECUTOR_SUBAGENT_ID). */
export const EXECUTOR_TARGET = "executor";

/** Mirrors the backend validators in app/agents/skills/models.py. */
export const MAX_SKILL_NAME_LENGTH = 64;
export const MAX_SKILL_DESCRIPTION_LENGTH = 1024;
export const SKILL_NAME_PATTERN = /^[a-z0-9]([a-z0-9-]*[a-z0-9])?$/;
/** The backend rejects consecutive hyphens separately from the pattern. */
export const CONSECUTIVE_HYPHENS = /--/;

/**
 * Accepts a GitHub repo reference: `owner/repo` (optionally with a sub-path) or
 * a full github.com URL. Mirrors what the backend's _parse_github_url handles.
 */
export const GITHUB_REPO_PATTERN =
  /^(https?:\/\/(www\.)?github\.com\/[\w.-]+\/[\w.-]+(\/.*)?|[\w.-]+\/[\w.-]+(\/.*)?)$/;
