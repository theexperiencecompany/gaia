"use client";

import { useReducedMotion } from "motion/react";
import { useCallback, useEffect, useState } from "react";

import { isOfferLive } from "@/config/offer";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import {
  DISCOUNT_CODE,
  DISCOUNT_PERCENT,
  LETTER_DISMISSED_KEY,
  LETTER_OPENED_KEY,
  SALUTATION_FALLBACK,
} from "@/features/chat/components/interface/founder-letter/content";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

/** The letter's standing offer, as the upgrade modal takes it. */
const LETTER_OFFER = {
  discountCode: DISCOUNT_CODE,
  discountPercent: DISCOUNT_PERCENT,
};

/**
 * The letter's state machine: what has been seen, what is still on offer, and
 * every side effect the envelope and the modal can fire.
 */
export function useFounderLetter(hidden: boolean) {
  const [isLetterOpen, setIsLetterOpen] = useState(false);
  // Both read in an effect, not in render, so server and client markup match.
  const [dismissed, setDismissed] = useState(false);
  const [hasOpened, setHasOpened] = useState(false);
  // An expired code fails loudly at Dodo's checkout, so the letter stops
  // offering it rather than sending readers into a 500.
  const [offerLive, setOfferLive] = useState(false);
  const [copied, setCopied] = useState(false);
  const userName = useCurrentUser().name;
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);
  const reduceMotion = useReducedMotion();

  const firstName = userName.trim().split(" ")[0] || SALUTATION_FALLBACK;

  useEffect(() => {
    const isDismissed = !!window.localStorage.getItem(LETTER_DISMISSED_KEY);
    setDismissed(isDismissed);
    setHasOpened(!!window.localStorage.getItem(LETTER_OPENED_KEY));
    setOfferLive(isOfferLive());
    // The denominator for every other event in this funnel: without it, an
    // open rate has no base to divide by.
    if (!isDismissed) {
      trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_SHOWN, {
        discount_code: DISCOUNT_CODE,
      });
    }
  }, []);

  const openLetter = useCallback(() => {
    const firstOpen = !window.localStorage.getItem(LETTER_OPENED_KEY);
    window.localStorage.setItem(LETTER_OPENED_KEY, "1");
    setHasOpened(true);
    setIsLetterOpen(true);
    trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_OPENED, {
      first_open: firstOpen,
      discount_code: DISCOUNT_CODE,
      discount_percent: DISCOUNT_PERCENT,
    });
  }, []);

  // Dismissing hides the envelope for good on this device.
  const dismissLetter = useCallback(() => {
    window.localStorage.setItem(LETTER_DISMISSED_KEY, "1");
    setDismissed(true);
    trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_DISMISSED, {
      discount_code: DISCOUNT_CODE,
    });
  }, []);

  const closeLetter = useCallback(() => setIsLetterOpen(false), []);

  // Voice mode hides the letter. Hiding it is derived, not an effect: the
  // early return in the component stops rendering while `hidden`, which takes
  // an open modal with it — otherwise the body scroll would stay locked with
  // nothing on screen to explain why.
  // Voice mode hiding the letter must CLOSE it for good (master's documented
  // intent): once `hidden`, clear the open flag via render-time adjustment so
  // exiting voice mode doesn't resurrect the modal. Render-phase setState is
  // React's sanctioned pattern here — no adjustment effect needed.
  if (hidden && isLetterOpen) {
    setIsLetterOpen(false);
  }
  const isOpen = isLetterOpen && !hidden;

  const copyCode = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(DISCOUNT_CODE);
    } catch {
      // Clipboard API can be unavailable (permissions, non-secure context);
      // fall back to the legacy path so the code still reaches the user.
      const textarea = document.createElement("textarea");
      textarea.value = DISCOUNT_CODE;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopied(true);
    trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_CODE_COPIED, {
      discount_code: DISCOUNT_CODE,
    });
    toast.success(`Code ${DISCOUNT_CODE} copied, it's yours`);
    window.setTimeout(() => setCopied(false), 2000);
  }, []);

  const claimOffer = useCallback(() => {
    trackEvent(ANALYTICS_EVENTS.FOUNDER_LETTER_DISCOUNT_CTA_CLICKED, {
      discount_code: DISCOUNT_CODE,
      discount_percent: DISCOUNT_PERCENT,
    });
    openUpgradeModal(LETTER_OFFER, {
      dismissible: true,
      source: "founder_letter",
    });
    closeLetter();
  }, [openUpgradeModal, closeLetter]);

  return {
    firstName,
    dismissed,
    hasOpened,
    offerLive,
    copied,
    isOpen,
    reduceMotion,
    openLetter,
    dismissLetter,
    closeLetter,
    copyCode,
    claimOffer,
  };
}
