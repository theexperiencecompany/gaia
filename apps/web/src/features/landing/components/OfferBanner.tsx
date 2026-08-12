"use client";

import { CancelIcon, CircleArrowRight02Icon } from "@icons";
import { useEffect, useState } from "react";

import {
  isOfferLive,
  OFFER_CODE,
  OFFER_EXPIRES_LABEL,
  OFFER_PERCENT,
} from "@/config/offer";
import { Link } from "@/i18n/navigation";
import { ANALYTICS_EVENTS, trackEvent } from "@/lib/analytics";

/** localStorage key: dismissing the banner keeps it gone on this device. */
const BANNER_DISMISSED_KEY = "gaia_offer_banner_dismissed";

/** Height of the strip, in pixels. The navbar offsets itself by this much. */
export const OFFER_BANNER_HEIGHT = 36;

/**
 * A slim strip above the navbar selling the early-bird offer, and the reason
 * the navbar sits lower on landing pages while it is up.
 *
 * It removes itself in three cases: the offer has expired, the visitor closed
 * it, or the first render has not happened yet (the dismissal lives in
 * localStorage, so it can only be read on the client — rendering it in the
 * same pass would mismatch the server markup).
 */
export function OfferBanner({ onVisibilityChange }: OfferBannerProps) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const show =
      isOfferLive() && !window.localStorage.getItem(BANNER_DISMISSED_KEY);
    setVisible(show);
    onVisibilityChange?.(show);
    if (show) {
      trackEvent(ANALYTICS_EVENTS.OFFER_BANNER_SHOWN, {
        discount_code: OFFER_CODE,
      });
    }
  }, [onVisibilityChange]);

  if (!visible) return null;

  const dismiss = () => {
    window.localStorage.setItem(BANNER_DISMISSED_KEY, "1");
    setVisible(false);
    onVisibilityChange?.(false);
    trackEvent(ANALYTICS_EVENTS.OFFER_BANNER_DISMISSED, {
      discount_code: OFFER_CODE,
    });
  };

  return (
    <div
      className="fixed inset-x-0 top-0 z-[60] flex items-center justify-center gap-3 bg-primary px-10 text-black"
      style={{ height: OFFER_BANNER_HEIGHT }}
    >
      <Link
        href="/pricing"
        onClick={() =>
          trackEvent(ANALYTICS_EVENTS.OFFER_BANNER_CLICKED, {
            discount_code: OFFER_CODE,
          })
        }
        className="group flex items-center gap-2 text-xs font-medium sm:text-sm"
      >
        <span className="rounded-full bg-black/15 px-2 py-0.5 text-[11px] font-semibold">
          Early bird
        </span>
        <span>
          <span className="font-semibold">{OFFER_PERCENT}% off</span> your first
          payment with{" "}
          <span className="font-semibold tracking-wide">{OFFER_CODE}</span>
          <span className="hidden sm:inline">
            , until {OFFER_EXPIRES_LABEL}
          </span>
        </span>
        <CircleArrowRight02Icon className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
      </Link>
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss the offer"
        className="absolute right-3 flex h-6 w-6 cursor-pointer items-center justify-center rounded-full outline-none transition-colors hover:bg-black/10 focus-visible:ring-2 focus-visible:ring-black/50"
      >
        <CancelIcon className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

interface OfferBannerProps {
  /** Lets the layout push the navbar down while the strip is up. */
  onVisibilityChange?: (visible: boolean) => void;
}
