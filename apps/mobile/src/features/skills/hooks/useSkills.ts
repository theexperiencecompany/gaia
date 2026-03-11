import { useCallback, useEffect, useState } from "react";
import type { Skill } from "../api/skills-api";
import { discoverSkills, getSkills } from "../api/skills-api";

export interface UseSkillsResult {
  mySkills: Skill[];
  discoverableSkills: Skill[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
}

export function useSkills(): UseSkillsResult {
  const [mySkills, setMySkills] = useState<Skill[]>([]);
  const [discoverableSkills, setDiscoverableSkills] = useState<Skill[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(async (refresh = false) => {
    if (refresh) {
      setIsRefreshing(true);
    } else {
      setIsLoading(true);
    }
    setError(null);

    try {
      const [owned, available] = await Promise.all([
        getSkills(),
        discoverSkills(),
      ]);

      const ownedIds = new Set(owned.map((s) => s.id));
      setMySkills(owned);
      setDiscoverableSkills(available.filter((s) => !ownedIds.has(s.id)));
    } catch (err) {
      setError(err instanceof Error ? err : new Error("Failed to load skills"));
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const refresh = useCallback(() => load(true), [load]);

  return {
    mySkills,
    discoverableSkills,
    isLoading,
    isRefreshing,
    error,
    refresh,
  };
}
