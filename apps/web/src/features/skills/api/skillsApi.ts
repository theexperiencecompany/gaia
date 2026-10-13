import { api } from "@/lib/api/typed";
import type { SkillInlineCreateRequest, SkillUpdateRequest } from "./types";

export const skillsApi = {
  /** List the current user's installed skills. */
  listSkills: () => api.get("/api/v1/skills"),

  /** List the targets a skill can run in (executor + connected subagents). */
  listTargets: () => api.get("/api/v1/skills/targets", { silent: true }),

  /** List the read-only built-in skills shipped with GAIA. */
  listBuiltinSkills: () => api.get("/api/v1/skills/builtin", { silent: true }),

  /** Create a skill from inline components. */
  createSkill: (body: SkillInlineCreateRequest) =>
    api.post("/api/v1/skills/install/inline", { body }),

  /** Edit an existing skill (description / instructions / target). */
  updateSkill: (skillId: string, body: SkillUpdateRequest) =>
    api.put("/api/v1/skills/{skill_id}", { path: { skill_id: skillId }, body }),

  /** Uninstall a skill and delete its files. */
  deleteSkill: async (skillId: string): Promise<void> => {
    await api.delete("/api/v1/skills/{skill_id}", {
      path: { skill_id: skillId },
    });
  },

  /** Enable a disabled skill. */
  enableSkill: async (skillId: string): Promise<void> => {
    await api.patch("/api/v1/skills/{skill_id}/enable", {
      path: { skill_id: skillId },
      silent: true,
    });
  },

  /** Disable a skill without uninstalling it. */
  disableSkill: async (skillId: string): Promise<void> => {
    await api.patch("/api/v1/skills/{skill_id}/disable", {
      path: { skill_id: skillId },
      silent: true,
    });
  },

  /** Preview the skills available in a GitHub repo without installing. */
  discoverSkills: (repo: string, branch = "main") =>
    api.get("/api/v1/skills/discover", { query: { repo, branch } }),

  /** Install a skill from a GitHub repo using its exact discovered path
   * (avoids picking the wrong skill when a repo has duplicate names). */
  installFromGithub: (
    repoUrl: string,
    skillName: string,
    skillPath: string,
    target?: string,
  ) =>
    api.post("/api/v1/skills/install/github", {
      query: {
        repo_url: repoUrl,
        skill_name: skillName,
        skill_path: skillPath,
        target,
      },
    }),
};
