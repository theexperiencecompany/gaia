"use client";

import type { QuietHours } from "@gaia/shared/types";
import { useEffect, useState } from "react";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";

interface UseQuietHoursSettings {
  /** null until the stored window loads; nothing is shown as stored before then. */
  quietHours: QuietHours | null;
  /** The stored window could not be read; the API client has already reported why. */
  loadFailed: boolean;
  saving: boolean;
  setEdge: (edge: keyof QuietHours, hour: number) => Promise<void>;
}

/**
 * Owns the user's quiet hours: the stored window, saved on every change and
 * rolled back on failure.
 */
export function useQuietHoursSettings(): UseQuietHoursSettings {
  const [quietHours, setQuietHours] = useState<QuietHours | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    NotificationsAPI.getQuietHours().then(setQuietHours, () =>
      setLoadFailed(true),
    );
  }, []);

  const setEdge = async (edge: keyof QuietHours, hour: number) => {
    if (!quietHours || quietHours[edge] === hour) return;
    const next = { ...quietHours, [edge]: hour };
    if (next.start_hour === next.end_hour) {
      toast.error("Quiet hours must start and end at different hours.");
      return;
    }
    const previous = quietHours;
    setQuietHours(next);
    setSaving(true);
    try {
      setQuietHours(await NotificationsAPI.updateQuietHours(next));
    } catch {
      setQuietHours(previous);
      toast.error("Couldn't save your quiet hours.");
    } finally {
      setSaving(false);
    }
  };

  return { quietHours, loadFailed, saving, setEdge };
}
