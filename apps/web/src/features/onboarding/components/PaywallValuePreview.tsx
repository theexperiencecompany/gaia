"use client";

import { Chip } from "@heroui/chip";
import { Skeleton } from "@heroui/skeleton";
import { CheckmarkCircle02Icon } from "@icons";
import * as m from "motion/react-m";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";

import { isKnownNeed } from "../constants";
import {
  NEED_WEEK_ONE,
  VALUE_PREVIEW_HEADING,
  VALUE_PREVIEW_JOBS_HEADING,
  VALUE_PREVIEW_TRUST_LINE,
  valuePreviewOtherNeedLine,
} from "../constants/messages";
import { MOTION_FADE_UP } from "../constants/motion";

/** Placeholder chips while the drafted jobs are still being written. */
const JOB_PLACEHOLDERS = ["first", "second"] as const;

interface PaywallValuePreviewProps {
  /** The jobs drafted from the user's answers; empty until the draft lands. */
  startingJobs: string[];
  jobsStillDrafting: boolean;
}

/**
 * What GAIA does for this user in week one, built from their Q2 picks, with
 * the jobs the background draft wrote from those answers once they land.
 */
export function PaywallValuePreview({
  startingJobs,
  jobsStillDrafting,
}: PaywallValuePreviewProps) {
  const preferences = useCurrentUser().onboarding?.preferences;
  const weekOne = (preferences?.needs ?? [])
    .filter(isKnownNeed)
    .map((need) => NEED_WEEK_ONE[need]);
  const otherNeed = preferences?.other_need?.trim();
  if (otherNeed) weekOne.push(valuePreviewOtherNeedLine(otherNeed));

  return (
    <div className="flex w-full max-w-sm flex-col gap-4 rounded-2xl bg-zinc-800 p-4">
      <p className="text-sm font-medium text-zinc-100">
        {VALUE_PREVIEW_HEADING}
      </p>
      <ul className="flex flex-col gap-2.5">
        {weekOne.map((line) => (
          <li key={line} className="flex items-start gap-2.5">
            <CheckmarkCircle02Icon className="mt-0.5 size-4 shrink-0 text-primary" />
            <span className="text-sm font-light text-zinc-300">{line}</span>
          </li>
        ))}
      </ul>
      {(startingJobs.length > 0 || jobsStillDrafting) && (
        <div className="flex flex-col gap-2 rounded-2xl bg-zinc-900 p-3">
          <p className="text-xs text-zinc-400">{VALUE_PREVIEW_JOBS_HEADING}</p>
          <div className="flex flex-wrap gap-2">
            {startingJobs.length > 0
              ? startingJobs.map((job) => (
                  <m.div key={job} {...MOTION_FADE_UP}>
                    <Chip size="sm" variant="flat">
                      {job}
                    </Chip>
                  </m.div>
                ))
              : JOB_PLACEHOLDERS.map((slot) => (
                  <Skeleton key={slot} className="h-6 w-28 rounded-full" />
                ))}
          </div>
        </div>
      )}
      <p className="text-xs font-light text-zinc-500">
        {VALUE_PREVIEW_TRUST_LINE}
      </p>
    </div>
  );
}
