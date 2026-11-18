"use client";

import type { BriefFreeDelivery } from "@gaia/shared";
import type { BriefingScheduleState } from "@gaia/shared/types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  type BriefsOffBlock,
  briefingApi,
  briefingKeys,
  briefingScheduleQuery,
  readBriefsOffBlock,
} from "@/features/briefing";
import { toast } from "@/lib/toast";

type ScheduleChange = Partial<
  Pick<BriefingScheduleState, "frequency" | "hour">
>;

interface ScheduleSave {
  next: BriefingScheduleState;
  deliveries?: Record<string, BriefFreeDelivery>;
}

interface UseBriefingScheduleSettings {
  /** null until the stored schedule loads; nothing is shown as stored before then. */
  schedule: BriefingScheduleState | null;
  /** The stored schedule could not be read. */
  loadFailed: boolean;
  refetch: () => void;
  saving: boolean;
  update: (change: ScheduleChange) => void;
  /** Set while turning briefs off waits on a new delivery for each brief workflow. */
  briefsOffBlock: BriefsOffBlock | null;
  /** Turn briefs off, moving each brief workflow to its chosen delivery. */
  turnOff: (deliveries: Record<string, BriefFreeDelivery>) => void;
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
  const qc = useQueryClient();
  const { data, isError, refetch } = useQuery(briefingScheduleQuery());
  const [briefsOffBlock, setBriefsOffBlock] = useState<BriefsOffBlock | null>(
    null,
  );

  const mutation = useMutation({
    mutationFn: ({ next, deliveries }: ScheduleSave) =>
      briefingApi.updateSchedule({
        frequency: next.frequency,
        hour: next.hour,
        workflow_deliveries: deliveries,
      }),
    onMutate: async ({ next }) => {
      await qc.cancelQueries({ queryKey: briefingKeys.schedule });
      const previous = qc.getQueryData(briefingKeys.schedule);
      qc.setQueryData(briefingKeys.schedule, next);
      return { previous };
    },
    onSuccess: (stored) => {
      qc.setQueryData(briefingKeys.schedule, stored);
      setBriefsOffBlock(null);
    },
    onError: (error, _save, context) => {
      qc.setQueryData(briefingKeys.schedule, context?.previous);
      const block = readBriefsOffBlock(error);
      if (block) setBriefsOffBlock(block);
      else toast.error(SAVE_FAILED);
    },
  });

  const schedule = data ?? null;

  return {
    schedule,
    loadFailed: isError,
    refetch: () => void refetch(),
    saving: mutation.isPending,
    update: (change) => {
      if (!schedule) return;
      const next = { ...schedule, ...change };
      if (next.frequency === schedule.frequency && next.hour === schedule.hour)
        return;
      mutation.mutate({ next });
    },
    briefsOffBlock,
    turnOff: (deliveries) => {
      if (!schedule) return;
      mutation.mutate({ next: { ...schedule, frequency: "off" }, deliveries });
    },
    keepBriefs: () => setBriefsOffBlock(null),
  };
}
