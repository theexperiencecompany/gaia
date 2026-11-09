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

  // One scope runs saves in order, so an earlier PATCH never lands after a later one. The API
  // layer already told the user about a failed save; the slider goes back to what is stored.
  const mutation = useMutation({
    scope: { id: QUIET_HOURS_KEY.join("/") },
    mutationFn: (next: QuietHours) => quietHoursApi.update(next),
    onSuccess: (stored) => qc.setQueryData(QUIET_HOURS_KEY, stored),
    onSettled: (_stored, _error, next) =>
      setDraft((current) => (current === next ? null : current)),
  });

  return {
    hours: draft ?? saved ?? null,
    preview: setDraft,
    save: (next: QuietHours) => {
      setDraft(next);
      mutation.mutate(next);
    },
  };
}
