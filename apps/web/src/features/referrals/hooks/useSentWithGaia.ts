"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { authApi } from "@/features/auth/api/authApi";
import {
  patchCurrentUser,
  useCurrentUser,
} from "@/features/auth/hooks/useCurrentUser";
import { mergedOnboardingUpdate } from "@/lib/onboardingPreferences";
import { toast } from "@/lib/toast";
import { SENT_WITH_GAIA_COPY } from "../referralCopy";

/** The opt-in "Sent with GAIA" line on mail GAIA writes; off until the user turns it on. */
export function useSentWithGaia() {
  const user = useCurrentUser();
  const queryClient = useQueryClient();
  const [isSaving, setIsSaving] = useState(false);
  const isEnabled = user.onboarding?.preferences?.sent_with_gaia ?? false;

  const setEnabled = async (next: boolean) => {
    setIsSaving(true);
    try {
      // PATCH only this field; the backend merges it into the stored preferences.
      const response = await authApi.updateOnboardingPreferences({
        sent_with_gaia: next,
      });
      if (!response.success) throw new Error(response.message);
      patchCurrentUser(
        queryClient,
        mergedOnboardingUpdate(user.onboarding, { sent_with_gaia: next }),
      );
    } catch {
      toast.error(SENT_WITH_GAIA_COPY.saveFailed);
    } finally {
      setIsSaving(false);
    }
  };

  return { isEnabled, isSaving, setEnabled };
}
