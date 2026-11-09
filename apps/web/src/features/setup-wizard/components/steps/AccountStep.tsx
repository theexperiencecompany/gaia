/**
 * Wizard step 0 (fresh local-auth instances only) — create the instance's
 * administrator account. Every later wizard step writes provider credentials
 * through authenticated endpoints, so this must exist (and be signed in)
 * before any of them can succeed. Reuses the auth feature's SignupForm; on
 * success the backend session cookie is set and the wizard continues.
 */

"use client";

import { useQueryClient } from "@tanstack/react-query";
import * as m from "motion/react-m";
import { SignupForm } from "@/features/auth/components/SignupForm";
import { MOTION_FADE_UP } from "@/features/onboarding/constants/motion";
import { setupKeys } from "@/features/settings/api/queryKeys";

interface AccountStepProps {
  /** Fired after signup succeeds and the admin session is established. */
  onCreated: () => void;
}

export function AccountStep({ onCreated }: AccountStepProps) {
  const queryClient = useQueryClient();
  return (
    <m.div className="w-full" {...MOTION_FADE_UP}>
      <div className="w-full rounded-2xl bg-zinc-900 p-4">
        <SignupForm
          onCreated={() => {
            void queryClient.invalidateQueries({ queryKey: setupKeys.status });
            onCreated();
          }}
        />
      </div>
    </m.div>
  );
}
