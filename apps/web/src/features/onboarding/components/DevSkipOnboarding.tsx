"use client";

import { Button } from "@heroui/button";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useUserActions } from "@/features/auth/hooks/useUser";
import { userInfoToStoreUser } from "@/features/auth/utils/userInfoToStoreUser";
import { completeOnboarding } from "@/features/onboarding/api/onboardingApi";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { isDevelopment } from "@/lib/fetchAll";
import { toast } from "@/lib/toast";

/**
 * Dev-only (ENV=development) shortcut to skip onboarding by submitting sensible
 * default values, so developers don't have to click through the full flow on
 * every fresh account. Renders nothing in production.
 */
export function DevSkipOnboarding() {
  const router = useRouter();
  const { setUser, updateUser } = useUserActions();
  const [loading, setLoading] = useState(false);

  if (!isDevelopment()) return null;

  const skip = async () => {
    trackEvent(ANALYTICS_EVENTS.ONBOARDING_SKIPPED, { source: "dev_skip" });
    setLoading(true);
    try {
      const res = await completeOnboarding({
        profession: "engineering",
        needs: ["inbox", "todos"],
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      });
      if (res.user) setUser(userInfoToStoreUser(res.user));
      updateUser({ onboarding: { completed: true, phase: "completed" } });
      router.push("/c");
    } catch (error) {
      console.error("[DevSkipOnboarding] skip failed:", error);
      toast.error("Dev skip failed — check the console.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed bottom-4 left-4 z-50">
      <Button
        size="sm"
        radius="full"
        variant="flat"
        color="warning"
        isLoading={loading}
        onPress={skip}
      >
        Skip onboarding (dev only)
      </Button>
    </div>
  );
}
