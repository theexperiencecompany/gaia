import { apiService } from "@/lib/api/service";
import type {
  BuiltinSkillsResponse,
  DiscoverSkillsResponse,
  Skill,
  SkillInlineCreateRequest,
  SkillListResponse,
  SkillTargetsResponse,
  SkillUpdateRequest,
} from "./types";

export const skillsApi = {
  /** List the current user's installed skills. */
  listSkills: async (): Promise<SkillListResponse> => {
    return await apiService.get<SkillListResponse>("/skills");
  },

  /** List the targets a skill can run in (executor + connected subagents). */
  listTargets: async (): Promise<SkillTargetsResponse> => {
    return await apiService.get<SkillTargetsResponse>("/skills/targets", {
      silent: true,
    });
  },

  /** List the read-only built-in skills shipped with GAIA. */
  listBuiltinSkills: async (): Promise<BuiltinSkillsResponse> => {
    return await apiService.get<BuiltinSkillsResponse>("/skills/builtin", {
      silent: true,
    });
  },

  /** Create a skill from inline components. */
  createSkill: async (body: SkillInlineCreateRequest): Promise<Skill> => {
    return await apiService.post<Skill>("/skills/install/inline", body);
  },

  /** Edit an existing skill (description / instructions / target). */
  updateSkill: async (
    skillId: string,
    body: SkillUpdateRequest,
  ): Promise<Skill> => {
    return await apiService.put<Skill>(`/skills/${skillId}`, body);
  },

  /** Uninstall a skill and delete its files. */
  deleteSkill: async (skillId: string): Promise<void> => {
    await apiService.delete(`/skills/${skillId}`);
  },

  /** Enable a disabled skill. */
  enableSkill: async (skillId: string): Promise<void> => {
    await apiService.patch(`/skills/${skillId}/enable`, {}, { silent: true });
  },

  /** Disable a skill without uninstalling it. */
  disableSkill: async (skillId: string): Promise<void> => {
    await apiService.patch(`/skills/${skillId}/disable`, {}, { silent: true });
  },

  /** Preview the skills available in a GitHub repo without installing. */
  discoverSkills: async (
    repo: string,
    branch = "main",
  ): Promise<DiscoverSkillsResponse> => {
    return await apiService.get<DiscoverSkillsResponse>(
      `/skills/discover?repo=${encodeURIComponent(repo)}&branch=${encodeURIComponent(branch)}`,
    );
  },

  /** Install a skill from a GitHub repo by name (auto-discovers its path). */
  installFromGithub: async (
    repoUrl: string,
    skillName: string,
    target?: string,
  ): Promise<Skill> => {
    const params = new URLSearchParams({
      repo_url: repoUrl,
      skill_name: skillName,
    });
    if (target) params.set("target", target);
    return await apiService.post<Skill>(
      `/skills/install/github?${params.toString()}`,
      {},
    );
  },
};
