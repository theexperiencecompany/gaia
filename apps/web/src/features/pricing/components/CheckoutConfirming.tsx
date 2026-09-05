"use client";

import { Spinner } from "@heroui/spinner";

interface CheckoutConfirmingProps {
  /** Past the visible budget: the webhook is late, so say so rather than
   *  spinning silently. Polling continues underneath either way. */
  isLate: boolean;
}

/** Shown from the moment the Dodo overlay closes until the webhook lands. The
 *  webhook is the only thing that makes a subscription real, so this state —
 *  not the overlay's own events — is what stands between paying and paid. */
export function CheckoutConfirming({ isLate }: CheckoutConfirmingProps) {
  return (
    <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-800/50 p-5 text-center">
      <Spinner size="sm" />
      <p className="text-sm font-normal">Confirming your payment…</p>
      {isLate && (
        <p className="text-balance text-xs font-light text-zinc-400">
          This is taking longer than expected — your access unlocks the moment
          payment lands.
        </p>
      )}
    </div>
  );
}
