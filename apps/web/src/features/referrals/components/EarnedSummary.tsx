import type { ReferralMeResponse } from "@shared/api/generated";
import { formatDateUTC } from "@shared/utils";
import { REFERRAL_UI_COPY } from "../referralCopy";

interface EarnedSummaryProps {
  me: ReferralMeResponse;
  /** Lead with the months total, for layouts that show no progress bar. */
  withMonths?: boolean;
}

/** "3 free months earned · 2 friends on the way · Next bill moves to Dec 14", leaving out whatever is empty. */
export function EarnedSummary({ me, withMonths = false }: EarnedSummaryProps) {
  const pending = me.friends.filter((f) => f.status === "joined").length;
  const parts = [
    withMonths && me.months_earned > 0
      ? REFERRAL_UI_COPY.monthsEarned(me.months_earned)
      : null,
    pending > 0 ? REFERRAL_UI_COPY.onTheWay(pending) : null,
    me.months_applied > 0 && me.next_billing_date
      ? REFERRAL_UI_COPY.nextBill(formatDateUTC(me.next_billing_date))
      : null,
  ].filter((part): part is string => part !== null);

  if (parts.length === 0) return null;
  return (
    <p className="text-[13px] text-zinc-500 tabular-nums">
      {parts.join(" · ")}
    </p>
  );
}
