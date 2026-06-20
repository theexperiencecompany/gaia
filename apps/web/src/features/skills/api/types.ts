// Skill types mirror the backend's flat snake_case schema
// (apps/api/app/agents/skills/models.py). Responses are not camelized.

export type SkillSource = "github" | "url" | "upload" | "inline";

export interface Skill {
  id: string;
  user_id: string;
  name: string;
  description: string;
  /** Target agent: "executor" or a subagent agent_name (e.g. gmail_agent). */
  target: string;
  license: string | null;
  compatibility: string | null;
  metadata: Record<string, string>;
  allowed_tools: string[];
  body_content: string | null;
  vfs_path: string;
  enabled: boolean;
  source: SkillSource;
  source_url: string | null;
  installed_at: string;
  updated_at: string | null;
  files: string[];
}

export interface SkillListResponse {
  skills: Skill[];
  total: number;
}

/** A place a skill can run: the executor or a connected integration subagent. */
export interface SkillTarget {
  /** agent_name written to a skill's `target`. */
  value: string;
  label: string;
  /** Integration id used to resolve a logo (or "executor"). */
  icon: string;
  connected: boolean;
}

export interface SkillTargetsResponse {
  targets: SkillTarget[];
}

export interface BuiltinSkillInfo {
  slug: string;
  name: string;
  description: string;
  target: string;
  /** Display name of the owning agent. */
  group_label: string;
  /** Owning subagent id (or "executor") for logo resolution. */
  icon: string;
  /** Whether the owning agent is available (always-on or connected integration). */
  connected: boolean;
  /** SKILL.md markdown body, for the read-only preview modal. */
  body: string;
}

export interface BuiltinSkillsResponse {
  skills: BuiltinSkillInfo[];
  total: number;
}

export interface SkillInlineCreateRequest {
  name: string;
  description: string;
  instructions: string;
  target: string;
}

export interface SkillUpdateRequest {
  description?: string;
  instructions?: string;
  target?: string;
}

export interface DiscoveredSkill {
  name: string;
  description: string;
  path: string;
  repo_url: string;
  subagent_id: string;
}

export interface DiscoverSkillsResponse {
  repo: string;
  branch: string;
  skills: DiscoveredSkill[];
  count: number;
}
