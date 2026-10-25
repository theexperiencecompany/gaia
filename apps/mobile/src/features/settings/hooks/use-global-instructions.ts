import { GLOBAL_INSTRUCTIONS_SCOPE } from "@gaia/shared/constants/instructions";
import {
  editInstructions,
  type InstructionsEdit,
  viewInstructionsDraft,
} from "@gaia/shared/utils";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  type InstructionsResponse,
  settingsApi,
} from "@/features/settings/api/settings-api";
import type { SaveInstructionsResult } from "@/features/settings/types";

const GLOBAL_INSTRUCTIONS_KEY = ["instructions", GLOBAL_INSTRUCTIONS_SCOPE];

/**
 * The instructions GAIA follows in every conversation, edited as a local draft.
 * Saves are explicit and guarded by the loaded revision; a conflict leaves the draft intact.
 */
export function useGlobalInstructions() {
  const qc = useQueryClient();
  const [edit, setEdit] =
    useState<InstructionsEdit<InstructionsResponse> | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: GLOBAL_INSTRUCTIONS_KEY,
    queryFn: () => settingsApi.getInstructions(GLOBAL_INSTRUCTIONS_SCOPE),
  });

  const mutation = useMutation({
    mutationFn: ({
      content,
      baseRevision,
    }: {
      content: string;
      baseRevision: number;
    }) =>
      settingsApi.updateInstructions(GLOBAL_INSTRUCTIONS_SCOPE, {
        content,
        base_revision: baseRevision,
      }),
    onSuccess: (result) => {
      if (result.status !== "saved") return;
      qc.setQueryData<InstructionsResponse>(
        GLOBAL_INSTRUCTIONS_KEY,
        result.instructions,
      );
      setEdit(null);
    },
  });

  const { base, value, isDirty } = viewInstructionsDraft(edit, data);

  return {
    value,
    setValue: (content: string) =>
      setEdit((prev) => editInstructions(prev, content, data)),
    isLoaded: data !== undefined,
    isLoading,
    isSaving: mutation.isPending,
    isDirty,
    retryLoad: refetch,
    /** Save against the revision the edit started from; pass a conflict's currentRevision to overwrite the newer copy. */
    save: async (baseRevision?: number): Promise<SaveInstructionsResult> => {
      if (!base) throw new Error("Global instructions have not loaded yet");
      return mutation.mutateAsync({
        content: value,
        baseRevision: baseRevision ?? base.revision,
      });
    },
    /** Replace the draft with the server's current copy. */
    loadLatest: async (): Promise<void> => {
      await refetch({ throwOnError: true });
      setEdit(null);
    },
  };
}
