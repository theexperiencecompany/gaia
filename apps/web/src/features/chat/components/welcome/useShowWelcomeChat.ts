"use client";

import { useCallback, useEffect, useState } from "react";
import { useUserStore } from "@/stores/userStore";

const WELCOME_SEEN_KEY = "gaia.welcomeChat.seen.v1";

interface UseShowWelcomeChatReturn {
  showWelcome: boolean;
  dismissWelcome: () => void;
}

/**
 * Returns whether to render the post-onboarding welcome experience on the
 * new-chat surface (`/c`). Shows only once per user — after onboarding
 * completes — and is dismissed permanently the first time the user clicks
 * past it or sends a real message.
 */
export function useShowWelcomeChat(): UseShowWelcomeChatReturn {
  const onboarding = useUserStore((s) => s.onboarding);
  const userId = useUserStore((s) => s.userId);
  const [hydrated, setHydrated] = useState(false);
  const [seen, setSeen] = useState(true);

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(WELCOME_SEEN_KEY);
      setSeen(raw === "true");
    } catch {
      setSeen(true);
    }
    setHydrated(true);
  }, []);

  const dismissWelcome = useCallback(() => {
    setSeen(true);
    try {
      window.localStorage.setItem(WELCOME_SEEN_KEY, "true");
    } catch {
      // ignore quota / private-mode failures
    }
  }, []);

  const showWelcome =
    hydrated && !seen && !!userId && onboarding?.completed === true;

  return { showWelcome, dismissWelcome };
}
