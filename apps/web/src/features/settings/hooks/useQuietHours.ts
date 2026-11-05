"use client";

import type { QuietHours } from "@shared/api/generated";
import { useEffect, useState } from "react";
import { quietHoursApi } from "@/features/settings/api/quietHoursApi";

/**
 * Owns the user's quiet hours: the stored window, a draft while the slider is
 * dragged, and a save that rolls back to what is stored when it fails.
 */
export function useQuietHours() {
  const [saved, setSaved] = useState<QuietHours | null>(null);
  const [draft, setDraft] = useState<QuietHours | null>(null);

  useEffect(() => {
    quietHoursApi.fetch().then(setSaved);
  }, []);

  const save = async (next: QuietHours) => {
    setDraft(next);
    try {
      setSaved(await quietHoursApi.update(next));
    } catch {
      // The API layer already told the user; the slider goes back to what is stored.
    } finally {
      setDraft(null);
    }
  };

  return { hours: draft ?? saved, preview: setDraft, save };
}
