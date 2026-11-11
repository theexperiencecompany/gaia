"use client";

import { useEffect, useState } from "react";
import { useLoginModalActions } from "@/features/auth/hooks/useLoginModal";
import type { SetupStatus } from "@/features/settings/api/providersApi";

/**
 * Whether the wizard leads with account creation; null until status first loads.
 *
 * Captured once so the step list cannot shift when creating the account flips
 * has_admin_account mid-wizard. While true, the global login modal stays
 * suppressed: its only action is WorkOS OAuth, which self-host lacks.
 */
export function useAccountStepGate(
  status: SetupStatus | undefined,
): boolean | null {
  const { suppressModal, unsuppressModal } = useLoginModalActions();
  const [needsAccountStep, setNeedsAccountStep] = useState<boolean | null>(
    null,
  );

  if (status && needsAccountStep === null) {
    setNeedsAccountStep(
      status.auth_mode === "local" && !status.has_admin_account,
    );
  }

  useEffect(() => {
    if (!needsAccountStep) return;
    suppressModal();
    return () => unsuppressModal();
  }, [needsAccountStep, suppressModal, unsuppressModal]);

  return needsAccountStep;
}
