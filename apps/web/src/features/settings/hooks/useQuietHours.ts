"use client";

import type { QuietHours } from "@shared/api/generated";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { quietHoursApi } from "@/features/settings/api/quietHoursApi";

const QUIET_HOURS_KEY = ["user", "quiet-hours"] as const;

/**
 * Owns the user's quiet hours: the stored window, a draft while the slider is
 * dragged, and a save that rolls back to what is stored when it fails.
 */
export function useQuietHours() {
  const qc = useQueryClient();
  const [draft, setDraft] = useState<QuietHours | null>(null);

  const { data: saved } = useQuery({
    queryKey: QUIET_HOURS_KEY,
    queryFn: quietHoursApi.fetch,
  });

  // The API layer already told the user about a failed save; the slider goes back to what is stored.
  const mutation = useMutation({
    mutationFn: (next: QuietHours) => quietHoursApi.update(next),
    onMutate: setDraft,
    onSuccess: (stored) => qc.setQueryData(QUIET_HOURS_KEY, stored),
    onSettled: () => setDraft(null),
  });

  return {
    hours: draft ?? saved ?? null,
    preview: setDraft,
    save: (next: QuietHours) => mutation.mutate(next),
  };
}
