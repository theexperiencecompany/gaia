"use client";

import type { BriefFreeDelivery } from "@gaia/shared";
import type { BriefingSchedule } from "@gaia/shared/types";
import { useEffect, useState } from "react";
import { toast } from "@/lib/toast";
import {
  type BriefsOffBlock,
  NotificationsAPI,
  readBriefsOffBlock,
} from "@/services/api/notifications";

interface UseBriefingScheduleSettings {
  /** null until the stored schedule loads; nothing is shown as stored before then. */
  schedule: BriefingSchedule | null;
  /** The stored schedule could not be read; the API client has already reported why. */
  loadFailed: boolean;
  saving: boolean;
  update: (change: Partial<BriefingSchedule>) => Promise<void>;
  /** Set while turning briefs off waits on a new delivery for each brief workflow. */
  briefsOffBlock: BriefsOffBlock | null;
  /** Turn briefs off, moving each brief workflow to its chosen delivery. */
  turnOff: (deliveries: Record<string, BriefFreeDelivery>) => Promise<void>;
  /** Drop the refused "off" and keep the schedule as stored. */
  keepBriefs: () => void;
}

const SAVE_FAILED = "Couldn't save your briefing schedule.";

/**
 * Owns the user's briefing schedule: how often briefs come and the daily
 * brief's hour, saved on every change and rolled back on failure. Turning
 * briefs off while workflows deliver to the brief is refused by the API; the
 * refusal is kept as briefsOffBlock until those workflows get a new delivery.
 */
export function useBriefingScheduleSettings(): UseBriefingScheduleSettings {
  const [schedule, setSchedule] = useState<BriefingSchedule | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [briefsOffBlock, setBriefsOffBlock] = useState<BriefsOffBlock | null>(
    null,
  );

  useEffect(() => {
    NotificationsAPI.getBriefingSchedule().then(setSchedule, () =>
      setLoadFailed(true),
    );
  }, []);

  const save = async (
    previous: BriefingSchedule,
    next: BriefingSchedule,
    deliveries?: Record<string, BriefFreeDelivery>,
  ) => {
    setSchedule(next);
    setSaving(true);
    try {
      setSchedule(
        await NotificationsAPI.updateBriefingSchedule({
          ...next,
          workflow_deliveries: deliveries,
        }),
      );
      setBriefsOffBlock(null);
    } catch (error) {
      setSchedule(previous);
      const block = readBriefsOffBlock(error);
      if (block) setBriefsOffBlock(block);
      else toast.error(SAVE_FAILED);
    } finally {
      setSaving(false);
    }
  };

  const update = async (change: Partial<BriefingSchedule>) => {
    if (!schedule) return;
    const next = { ...schedule, ...change };
    if (next.frequency === schedule.frequency && next.hour === schedule.hour)
      return;
    await save(schedule, next);
  };

  const turnOff = async (deliveries: Record<string, BriefFreeDelivery>) => {
    if (!schedule) return;
    await save(schedule, { ...schedule, frequency: "off" }, deliveries);
  };

  return {
    schedule,
    loadFailed,
    saving,
    update,
    briefsOffBlock,
    turnOff,
    keepBriefs: () => setBriefsOffBlock(null),
  };
}
