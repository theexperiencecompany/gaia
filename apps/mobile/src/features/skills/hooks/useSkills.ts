import { useEffect, useState } from "react";
import type { DiscoveredSkill, Skill } from "../api/skills-api";
import { discoverSkills, getSkills } from "../api/skills-api";

export interface UseSkillsResult {
  mySkills: Skill[];
  discoverableSkills: DiscoveredSkill[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

interface SkillSets {
  mySkills: Skill[];
  discoverableSkills: DiscoveredSkill[];
}

/** Owned skills, and the discoverable ones the user does not already own. */
async function fetchSkillSets(): Promise<SkillSets> {
  const [owned, available] = await Promise.all([getSkills(), discoverSkills()]);
  const ownedNames = new Set(owned.map((s) => s.name));
  return {
    mySkills: owned,
    discoverableSkills: available.filter((s) => !ownedNames.has(s.name)),
  };
}

const asError = (err: unknown): Error =>
  err instanceof Error ? err : new Error("Failed to load skills");

export function useSkills(): UseSkillsResult {
  const [sets, setSets] = useState<SkillSets>({
    mySkills: [],
    discoverableSkills: [],
  });
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let active = true;
    fetchSkillSets()
      .then((loaded) => {
        if (active) setSets(loaded);
      })
      .catch((err: unknown) => {
        if (active) setError(asError(err));
      })
      .then(() => {
        if (active) setIsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const refresh = async () => {
    setIsRefreshing(true);
    setError(null);
    try {
      setSets(await fetchSkillSets());
    } catch (err) {
      setError(asError(err));
    }
    // Not a `finally`: React Compiler cannot compile one, and the catch above
    // swallows, so this runs on every path anyway.
    setIsRefreshing(false);
  };

  return { ...sets, isLoading, isRefreshing, error, refresh };
}
