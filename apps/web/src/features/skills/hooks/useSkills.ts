"use client";

import { useCallback, useEffect, useState } from "react";
import { toast } from "@/lib/toast";
import { skillsApi } from "../api/skillsApi";
import type { Skill, SkillTarget } from "../api/types";

export interface UseSkillsResult {
  skills: Skill[];
  targets: SkillTarget[];
  loading: boolean;
  refetch: () => Promise<void>;
  setEnabled: (skill: Skill, enabled: boolean) => Promise<void>;
  removeSkill: (skill: Skill) => Promise<boolean>;
}

/**
 * Loads the user's installed skills plus the targets they can run in, and
 * exposes enable/disable/delete actions with optimistic local updates.
 */
export function useSkills(): UseSkillsResult {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [targets, setTargets] = useState<SkillTarget[]>([]);
  const [loading, setLoading] = useState(true);

  const refetch = useCallback(async () => {
    try {
      const [list, targetsResponse] = await Promise.all([
        skillsApi.listSkills(),
        skillsApi.listTargets(),
      ]);
      setSkills(list.skills);
      setTargets(targetsResponse.targets);
    } catch {
      // listSkills isn't silent, so the API interceptor already surfaces a
      // toast; swallow here so the mount effect can't reject unhandled.
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const setEnabled = useCallback(async (skill: Skill, enabled: boolean) => {
    setSkills((prev) =>
      prev.map((s) => (s.id === skill.id ? { ...s, enabled } : s)),
    );
    try {
      if (enabled) await skillsApi.enableSkill(skill.id);
      else await skillsApi.disableSkill(skill.id);
    } catch {
      setSkills((prev) =>
        prev.map((s) => (s.id === skill.id ? { ...s, enabled: !enabled } : s)),
      );
      toast.error(
        `Failed to ${enabled ? "enable" : "disable"} "${skill.name}"`,
      );
    }
  }, []);

  const removeSkill = useCallback(async (skill: Skill) => {
    try {
      await skillsApi.deleteSkill(skill.id);
      setSkills((prev) => prev.filter((s) => s.id !== skill.id));
      toast.success(`Deleted "${skill.name}"`);
      return true;
    } catch {
      toast.error(`Failed to delete "${skill.name}"`);
      return false;
    }
  }, []);

  return { skills, targets, loading, refetch, setEnabled, removeSkill };
}
