import { useCallback, useState } from "react";

import type { Goal, GoalCreate, GoalUpdate } from "@/types/api/goalsApiTypes";

import { goalsApi } from "../api/goalsApi";

export const useGoals = () => {
  const [goals, setGoals] = useState<Goal[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchGoals = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await goalsApi.fetchGoals();
      setGoals(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to fetch goals");
    } finally {
      setLoading(false);
    }
  }, []);

  const createGoal = useCallback(async (goal: GoalCreate): Promise<Goal> => {
    try {
      setError(null);
      const newGoal = await goalsApi.createGoal(goal);
      setGoals((prev) => [newGoal, ...prev]);
      return newGoal;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create goal");
      throw err;
    }
  }, []);

  const updateGoal = useCallback(
    async (id: string, goal: GoalUpdate): Promise<Goal> => {
      try {
        setError(null);
        const updatedGoal = await goalsApi.updateGoal(id, goal);
        setGoals((prev) => prev.map((g) => (g.id === id ? updatedGoal : g)));
        return updatedGoal;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to update goal");
        throw err;
      }
    },
    [],
  );

  const deleteGoal = useCallback(async (id: string): Promise<void> => {
    try {
      setError(null);
      await goalsApi.deleteGoal(id);
      setGoals((prev) => prev.filter((g) => g.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete goal");
      throw err;
    }
  }, []);

  return {
    goals,
    loading,
    error,
    fetchGoals,
    createGoal,
    updateGoal,
    deleteGoal,
  };
};
