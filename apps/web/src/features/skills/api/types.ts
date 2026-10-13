// Skill types mirror the backend's flat snake_case schema
// (apps/api/app/agents/skills/models.py). Responses are not camelized.

export type {
  BuiltinSkillInfo,
  Skill,
  SkillInlineCreateRequest,
  SkillTarget,
  SkillUpdateRequest,
} from "@shared/api/generated";

/** A place a skill can run: the executor or a connected integration subagent. */

export interface DiscoveredSkill {
  name: string;
  description: string;
  path: string;
  repo_url: string;
  subagent_id: string;
}
