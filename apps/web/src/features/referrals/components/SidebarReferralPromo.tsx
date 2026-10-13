"use client";

import { GiftIcon } from "@icons";
import { useRouter } from "next/navigation";
import { SidebarPromo } from "@/components/layout/sidebar/SidebarPromo";
import { track } from "@/lib/analytics";
import { useShareLink } from "../hooks/useShareLink";
import { REFERRAL_COPY, REFERRAL_SIDEBAR_COPY } from "../referralCopy";
import type { ReferralCopyVariant } from "../types/contract";
import type { OfferPrices } from "../utils/offerPrices";

/** Where the card sends people whose browser has no share sheet. */
const REFERRALS_SETTINGS_HREF = "/settings/referrals";
const COLLAPSE_KEY = "sidebar-referral-collapsed:v1";

interface SidebarReferralPromoProps {
  url: string;
  prices: OfferPrices;
  copyVariant: ReferralCopyVariant;
}

/** The sidebar promo card, for Pro users: share the link where it can, else open the page. */
export function SidebarReferralPromo({
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
