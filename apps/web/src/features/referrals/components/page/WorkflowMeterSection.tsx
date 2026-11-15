import type { ReferralWorkflowMeter } from "@shared/api/generated";
import { REFERRAL_UI_COPY } from "../../referralCopy";

interface WorkflowMeterSectionProps {
  meter: ReferralWorkflowMeter;
}

/** Whether a creator has anything on their workflow meter worth a row: a published workflow, or credit from one. */
function hasWorkflowMeter(meter: ReferralWorkflowMeter): boolean {
  return meter.published > 0 || meter.subscribed > 0 || meter.months_earned > 0;
}

/** "From your workflows": paying visitors filling the next free month, below Friends. Visitors are counted, never named. */
export function WorkflowMeterSection({ meter }: WorkflowMeterSectionProps) {
  if (!hasWorkflowMeter(meter)) return null;
  const { subscribed, per_month: perMonth, months_earned: months } = meter;
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h2 className="text-sm font-medium text-zinc-300">
          {REFERRAL_UI_COPY.workflowsTitle}
        </h2>
        {months > 0 && (
          <span className="text-[13px] text-zinc-500 tabular-nums">
            {REFERRAL_UI_COPY.monthsEarned(months)}
          </span>
        )}
      </div>
      <div className="flex flex-col gap-3 rounded-2xl bg-zinc-900/60 px-4 py-3">
        <p className="text-sm text-zinc-200 tabular-nums">
          {subscribed === 0 && months === 0
            ? REFERRAL_UI_COPY.workflowMeterEmpty(perMonth)
            : REFERRAL_UI_COPY.workflowMeter(subscribed, perMonth)}
        </p>
        <div
          className="relative h-1.5 overflow-hidden rounded-full bg-zinc-700"
          role="progressbar"
          aria-valuemin={0}
          aria-valuemax={perMonth}
          aria-valuenow={subscribed}
          aria-label={REFERRAL_UI_COPY.workflowMeter(subscribed, perMonth)}
        >
          <div
            className="absolute inset-y-0 left-0 bg-zinc-100 transition-[width] duration-500 ease-out"
            style={{ width: `${(subscribed / perMonth) * 100}%` }}
          />
        </div>
      </div>
    </section>
  );
}
