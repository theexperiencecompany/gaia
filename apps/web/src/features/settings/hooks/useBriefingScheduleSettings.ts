"use client";

import type { BriefingSchedule } from "@gaia/shared/types";
import { useEffect, useState } from "react";
import { toast } from "@/lib/toast";
import { NotificationsAPI } from "@/services/api/notifications";

interface UseBriefingScheduleSettings {
  /** null until the stored schedule loads; nothing is shown as stored before then. */
  schedule: BriefingSchedule | null;
  /** The stored schedule could not be read; the API client has already reported why. */
  loadFailed: boolean;
  saving: boolean;
  update: (change: Partial<BriefingSchedule>) => Promise<void>;
}

/**
 * Owns the user's briefing schedule: how often briefs come and the daily
 * brief's hour, saved on every change and rolled back on failure.
 */
export function useBriefingScheduleSettings(): UseBriefingScheduleSettings {
  const [schedule, setSchedule] = useState<BriefingSchedule | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    NotificationsAPI.getBriefingSchedule().then(setSchedule, () =>
      setLoadFailed(true),
    );
  }, []);

  const update = async (change: Partial<BriefingSchedule>) => {
    if (!schedule) return;
    const next = { ...schedule, ...change };
    if (next.frequency === schedule.frequency && next.hour === schedule.hour)
      return;
    const previous = schedule;
    setSchedule(next);
    setSaving(true);
    try {
      setSchedule(await NotificationsAPI.updateBriefingSchedule(next));
    } catch {
      setSchedule(previous);
      toast.error("Couldn't save your briefing schedule.");
    } finally {
      setSaving(false);
    }
  };

  return { schedule, loadFailed, saving, update };
}
