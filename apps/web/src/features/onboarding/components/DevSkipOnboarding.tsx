"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useUser, useUserActions } from "@/features/auth/hooks/useUser";
import { userInfoToStoreUser } from "@/features/auth/utils/userInfoToStoreUser";
import { completeOnboarding } from "@/features/onboarding/api/onboardingApi";
import { isDevelopment } from "@/lib/fetchAll";
import { toast } from "@/lib/toast";

/**
 * Dev-only (ENV=development) shortcut to skip onboarding by submitting sensible
 * default values, so developers don't have to click through the full flow on
 * every fresh account. Renders nothing in production.
 */
export function DevSkipOnboarding() {
  const router = useRouter();
  const user = useUser();
  const { setUser, updateUser } = useUserActions();
  const [loading, setLoading] = useState(false);

  if (!isDevelopment()) return null;

  const skip = async () => {
    setLoading(true);
    try {
      const res = await completeOnboarding({
        name: user.name || "Dev User",
        profession: "Software Developer",
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        focus: "Testing GAIA in development",
      });
      if (res.user) setUser(userInfoToStoreUser(res.user));
      // Force completed locally so useOnboardingGuard routes to /c instead of
      // holding on /onboarding while the backend intelligence pipeline runs.
      updateUser({ onboarding: { completed: true, phase: "completed" } });
      router.push("/c");
    } catch (error) {
      console.error("[DevSkipOnboarding] skip failed:", error);
      toast.error("Dev skip failed — check the console.");
      setLoading(false);
    }
  };

  return (
    <div className="fixed bottom-4 left-4 z-50 flex items-center gap-2">
      <Chip size="sm" color="warning" variant="flat">
        dev only
      </Chip>
      <Button
        size="sm"
        radius="full"
        variant="flat"
        color="warning"
        isLoading={loading}
        onPress={skip}
      >
        Skip onboarding
      </Button>
    </div>
  );
}
