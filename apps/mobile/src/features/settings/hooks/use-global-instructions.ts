import { GLOBAL_INSTRUCTIONS_SCOPE } from "@gaia/shared/constants/instructions";
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
  const [draft, setDraft] = useState<string | null>(null);

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
      setDraft(null);
    },
  });

  const saved = data?.content ?? "";
  const value = draft ?? saved;

  return {
    value,
    setValue: setDraft,
    isLoaded: data !== undefined,
    isLoading,
    isSaving: mutation.isPending,
    isDirty: value !== saved,
    retryLoad: refetch,
    /** Save the draft; pass a conflict's currentRevision to overwrite the newer copy. */
    save: async (baseRevision?: number): Promise<SaveInstructionsResult> => {
      if (!data) throw new Error("Global instructions have not loaded yet");
      return mutation.mutateAsync({
        content: value,
        baseRevision: baseRevision ?? data.revision,
      });
    },
    /** Replace the draft with the server's current copy. */
    loadLatest: async (): Promise<void> => {
      await refetch({ throwOnError: true });
      setDraft(null);
    },
  };
}
