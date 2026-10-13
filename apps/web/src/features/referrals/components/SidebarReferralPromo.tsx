"use client";

import { GiftIcon } from "@icons";
import type { ReferralCopyVariant } from "@shared/api/generated";
import { useRouter } from "next/navigation";
import { SidebarPromo } from "@/components/layout/sidebar/SidebarPromo";
import { track } from "@/lib/analytics";
import { useReferralMe } from "../hooks/useReferrals";
import { useShareLink } from "../hooks/useShareLink";
import { REFERRAL_COPY, REFERRAL_SIDEBAR_COPY } from "../referralCopy";
import { type OfferPrices, offerPrices } from "../utils/offerPrices";

/** Where the card sends people whose browser has no share sheet. */
const REFERRALS_SETTINGS_HREF = "/settings/referrals";
const COLLAPSE_KEY = "sidebar-referral-collapsed:v1";

interface SidebarReferralPromoProps {
  url: string;
  prices: OfferPrices;
  copyVariant: ReferralCopyVariant;
}

/** The Pro user's sidebar slot: their live invite link, or nothing until it loads. */
export function SidebarReferralSlot() {
  const state = useReferralMe();
  if (state.status !== "ready") return null;
  return (
    <SidebarReferralPromo
      url={state.me.share_link}
      prices={offerPrices(state.me.offer)}
      copyVariant={state.me.copy_variant}
    />
  );
}

/** The sidebar promo card: share the link where the platform can, else open the page. */
function SidebarReferralPromo({
  url,
  prices,
  copyVariant,
}: SidebarReferralPromoProps) {
  const router = useRouter();
  const { share } = REFERRAL_COPY[copyVariant];
  const { canShareNatively, shareNatively } = useShareLink({
    surface: "sidebar",
    copyVariant,
    url,
    text: share.text(prices),
    emailSubject: share.emailSubject,
  });

  return (
    <SidebarPromo
      heading={REFERRAL_SIDEBAR_COPY.title}
      body={REFERRAL_SIDEBAR_COPY.body(prices)}
      isBodyLoading={false}
      cta={REFERRAL_SIDEBAR_COPY.cta}
      icon={<GiftIcon width={17} height={17} />}
      collapseKey={COLLAPSE_KEY}
      onCollapse={() =>
        track("referral:card_dismissed", {
          surface: "sidebar",
          copy_variant: copyVariant,
        })
      }
      onAction={() =>
        canShareNatively
          ? void shareNatively()
          : router.push(REFERRALS_SETTINGS_HREF)
      }
    />
  );
}
