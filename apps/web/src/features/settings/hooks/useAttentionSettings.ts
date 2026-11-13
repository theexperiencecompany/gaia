"use client";

import type { AttentionSettings } from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { attentionApi } from "@/features/settings/api/attentionApi";

const ATTENTION_KEY = ["user", "attention"] as const;

/**
 * Owns how much GAIA tells the user unprompted: the stored settings, a draft while the
 * budget slider is dragged, and a save that rolls back to what is stored when it fails.
 */
export function useAttentionSettings() {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<AttentionSettings | null>(null);

  const { data: saved } = useQuery({
    queryKey: ATTENTION_KEY,
    queryFn: attentionApi.fetch,
  });

  // One scope runs saves in order, so an earlier PUT never lands after a later one.
  const mutation = useMutation({
    scope: { id: ATTENTION_KEY.join("/") },
    mutationFn: (next: AttentionSettings) => attentionApi.update(next),
    onSuccess: (stored) => qc.setQueryData(ATTENTION_KEY, stored),
    onSettled: (_stored, _error, next) =>
      setDraft((current) => (current === next ? null : current)),
  });

  return {
    settings: draft ?? saved ?? null,
    preview: setDraft,
    save: (next: AttentionSettings) => {
      setDraft(next);
      mutation.mutate(next);
    },
  };
}
