// Skill types mirror the backend's flat snake_case schema
// (apps/api/app/agents/skills/models.py). Responses are not camelized.

export type {
  BuiltinSkillInfo,
  DiscoveredSkillInfo,
  Skill,
  SkillInlineCreateRequest,
  SkillTarget,
  SkillUpdateRequest,
} from "@shared/api/generated";
