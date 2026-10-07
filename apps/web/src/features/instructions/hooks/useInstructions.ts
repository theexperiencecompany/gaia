import type { InstructionsResponse } from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useState } from "react";
import { toast } from "@/lib/toast";

import {
  instructionsApi,
  instructionsConflictRevision,
  instructionsQueryOptions,
} from "../api/instructionsApi";

/** An in-progress edit, pinned to the record it started from so a refetch cannot move its base. */
interface InstructionsEdit {
  content: string;
  base: InstructionsResponse | undefined;
}

const errorMessage = (error: unknown, fallback: string): string =>
  error instanceof Error ? error.message : fallback;

/**
 * Load, edit and save one scope's instructions ("global" or an integration id).
 *
 * A save that loses a race to another writer (often GAIA itself) leaves the
 * draft untouched and raises hasConflict; the user then picks loadLatest or keepMine.
 */
export const useInstructions = (scope: string) => {
  const queryClient = useQueryClient();
  const query = useQuery(instructionsQueryOptions(scope));
  const [edit, setEdit] = useState<InstructionsEdit | null>(null);
  const [conflictRevision, setConflictRevision] = useState<number | null>(null);

  const base = edit?.base ?? query.data;
  const draft = edit?.content ?? base?.content ?? "";
  // Raw compare: the backend already normalizes whitespace-only content to empty.
  const isDirty = base !== undefined && draft !== base.content;

  const mutation = useMutation({
    mutationFn: (body: { content: string; base_revision: number }) =>
      instructionsApi.update(scope, body),
  });

  const setDraft = useCallback(
    (content: string) =>
      setEdit((prev) => ({ content, base: prev?.base ?? query.data })),
    [query.data],
  );

  const discard = useCallback(() => {
    setEdit(null);
    setConflictRevision(null);
  }, []);

  const { mutateAsync } = mutation;
  const commit = useCallback(
    async (baseRevision: number): Promise<boolean> => {
      try {
        const saved = await mutateAsync({
          content: draft,
          base_revision: baseRevision,
        });
        queryClient.setQueryData(
          instructionsQueryOptions(scope).queryKey,
          saved,
        );
        discard();
        toast.success("Instructions saved");
        return true;
      } catch (error) {
        const currentRevision = instructionsConflictRevision(error);
        if (currentRevision === null) {
          toast.error(errorMessage(error, "Failed to save instructions"));
          return false;
        }
        setConflictRevision(currentRevision);
        return false;
      }
    },
    [mutateAsync, draft, queryClient, scope, discard],
  );

  const save = useCallback(
    async () => (base ? commit(base.revision) : false),
    [base, commit],
  );

  const keepMine = useCallback(
    async () => (conflictRevision === null ? false : commit(conflictRevision)),
    [conflictRevision, commit],
  );

  const loadLatest = useCallback(async () => {
    try {
      await queryClient.fetchQuery(instructionsQueryOptions(scope));
      discard();
    } catch (error) {
      toast.error(
        errorMessage(error, "Failed to load the latest instructions"),
      );
    }
  }, [queryClient, scope, discard]);

  return {
    instructions: query.data,
    isLoading: query.isLoading,
    loadFailed: query.isError,
    isRefreshing: query.isFetching,
    draft,
    setDraft,
    isDirty,
    isSaving: mutation.isPending,
    hasConflict: conflictRevision !== null,
    save,
    keepMine,
    loadLatest,
    discard,
  };
};

export type UseInstructionsResult = ReturnType<typeof useInstructions>;
