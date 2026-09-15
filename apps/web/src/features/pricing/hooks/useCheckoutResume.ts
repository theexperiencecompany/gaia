"use client";

import { useEffect, useRef } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";

import {
  clearPendingCheckout,
  readPendingCheckout,
} from "../lib/pendingCheckout";
import { useDodoPayments } from "./useDodoPayments";

/**
 * Resumes a checkout a logged-out user started before signing up. Mounted
 * globally (GlobalAuth). Once authenticated with a valid pending plan, it
 * creates the subscription and redirects to the Dodo payment link. The flag is
 * cleared after the attempt settles: on success the page has already navigated
 * to Dodo; on failure the auth gates fall through to normal onboarding.
 */
export const useCheckoutResume = () => {
  const user = useCurrentUser();
  const { createSubscriptionAndRedirect } = useDodoPayments();
  const hasFired = useRef(false);

  useEffect(() => {
    if (!user.userId || hasFired.current) return;
    const planId = readPendingCheckout();
    if (!planId) return;
    hasFired.current = true;
    void createSubscriptionAndRedirect(planId, {
      source: "checkout_resume",
    }).finally(() => {
      clearPendingCheckout();
    });
  }, [user.userId, createSubscriptionAndRedirect]);
};
