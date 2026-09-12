// Skill types mirror the backend's flat snake_case schema
// (apps/api/app/agents/skills/models.py). Responses are not camelized.

import type { Schema } from "@shared/api/generated";

export type Skill = Schema<"Skill">;

export type SkillListResponse = Schema<"SkillListResponse">;

/** A place a skill can run: the executor or a connected integration subagent. */
export type SkillTarget = Schema<"SkillTarget">;

export type SkillTargetsResponse = Schema<"SkillTargetsResponse">;

export type BuiltinSkillInfo = Schema<"BuiltinSkillInfo">;

export type BuiltinSkillsResponse = Schema<"BuiltinSkillsResponse">;

export type SkillInlineCreateRequest = Schema<"SkillInlineCreateRequest">;

export type SkillUpdateRequest = Schema<"SkillUpdateRequest">;

export interface DiscoveredSkill {
  name: string;
  description: string;
  path: string;
  repo_url: string;
  subagent_id: string;
}

export type DiscoverSkillsResponse = Schema<"DiscoverSkillsResponse">;
