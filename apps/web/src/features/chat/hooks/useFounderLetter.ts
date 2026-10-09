"use client";

import { useReducedMotion } from "motion/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { isOfferLive } from "@/config/offer";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import {
  DISCOUNT_PERCENT,
  LETTER_DISMISSED_KEY,
  LETTER_OPENED_KEY,
  SALUTATION_FALLBACK,
} from "@/features/chat/components/interface/founder-letter/content";
import { useDiscountCodes } from "@/features/pricing/hooks/useDiscountCodes";
import { track } from "@/lib/analytics";
import { toast } from "@/lib/toast";
import { useUpgradeModalStore } from "@/stores/upgradeModalStore";

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
  const [offerWindowOpen, setOfferWindowOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const userName = useCurrentUser().name;
  const openUpgradeModal = useUpgradeModalStore((s) => s.openModal);
  const reduceMotion = useReducedMotion();

  const { data: discountCodes, isFetched: discountCodesFetched } =
    useDiscountCodes();
  const discountCode = discountCodes?.founder_letter ?? null;
  // No configured code means the letter carries no offer at all.
  const liveOfferCode = offerWindowOpen ? discountCode : null;

  const firstName = userName.trim().split(" ")[0] || SALUTATION_FALLBACK;

  // Whether the envelope appeared on this load, decided at mount: a reader who
  // dismisses it before the code arrives was still shown it.
  const shownOnMount = useRef(false);
  const shownTracked = useRef(false);

  useEffect(() => {
    const isDismissed = !!window.localStorage.getItem(LETTER_DISMISSED_KEY);
    shownOnMount.current = !isDismissed;
    setDismissed(isDismissed);
    setHasOpened(!!window.localStorage.getItem(LETTER_OPENED_KEY));
    setOfferWindowOpen(isOfferLive());
  }, []);

  // The denominator for every other event in this funnel: without it, an
  // open rate has no base to divide by. Sent once the code is known, so it
  // names the code the reader was actually offered.
  useEffect(() => {
    if (!discountCodesFetched || !shownOnMount.current || shownTracked.current)
      return;
    shownTracked.current = true;
    track("founder_letter:shown", {
      discount_code: discountCode ?? undefined,
    });
  }, [discountCodesFetched, discountCode]);

  const openLetter = useCallback(() => {
    const firstOpen = !window.localStorage.getItem(LETTER_OPENED_KEY);
    window.localStorage.setItem(LETTER_OPENED_KEY, "1");
    setHasOpened(true);
    setIsLetterOpen(true);
    track("founder_letter:opened", {
      first_open: firstOpen,
      discount_code: discountCode ?? undefined,
      discount_percent: DISCOUNT_PERCENT,
    });
  }, [discountCode]);

  // Dismissing hides the envelope for good on this device.
  const dismissLetter = useCallback(() => {
    window.localStorage.setItem(LETTER_DISMISSED_KEY, "1");
    setDismissed(true);
    track("founder_letter:dismissed", {
      discount_code: discountCode ?? undefined,
    });
  }, [discountCode]);

  const closeLetter = useCallback(() => setIsLetterOpen(false), []);

  // Voice mode hides the letter via a derived early return (not an effect) so
  // body scroll doesn't stay locked with nothing on screen; clearing
  // `isLetterOpen` here closes it for good, so exiting voice mode won't reopen it.
  if (hidden && isLetterOpen) {
    setIsLetterOpen(false);
  }
  const isOpen = isLetterOpen && !hidden;

  const copyCode = useCallback(async () => {
    if (discountCode === null) return;
    try {
      await navigator.clipboard.writeText(discountCode);
    } catch {
      // Clipboard API can be unavailable (permissions, non-secure context);
      // fall back to the legacy path so the code still reaches the user.
      const textarea = document.createElement("textarea");
      textarea.value = discountCode;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      textarea.remove();
    }
    setCopied(true);
    track("founder_letter:code_copied", {
      discount_code: discountCode ?? undefined,
    });
    toast.success(`Code ${discountCode} copied, it's yours`);
    window.setTimeout(() => setCopied(false), 2000);
  }, [discountCode]);

  const claimOffer = useCallback(() => {
    if (discountCode === null) return;
    track("founder_letter:discount_cta_clicked", {
      discount_code: discountCode,
      discount_percent: DISCOUNT_PERCENT,
    });
    openUpgradeModal(
      { discountCode, discountPercent: DISCOUNT_PERCENT },
      { dismissible: true, source: "founder_letter" },
    );
    closeLetter();
  }, [discountCode, openUpgradeModal, closeLetter]);

  return {
    firstName,
    dismissed,
    hasOpened,
    liveOfferCode,
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
