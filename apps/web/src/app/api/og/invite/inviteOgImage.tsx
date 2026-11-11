import type {
  ReferralCopyVariant,
  ReferralResolveResponse,
} from "@shared/api/generated";
import { ImageResponse } from "next/og";
import {
  REFERRAL_COPY,
  REFERRAL_UI_COPY,
} from "@/features/referrals/referralCopy";
import { offerPrices } from "@/features/referrals/utils/offerPrices";
import {
  colors,
  fonts,
  getOgCompatibleAvatarUrl,
  loadFonts,
  OG_HEIGHT,
  OG_WIDTH,
} from "../lib";
import { WallpaperCard } from "../wallpaperCard";
import { GiftTicketArt } from "./GiftTicketArt";
import { ReferrerFace } from "./ReferrerFace";

interface InviteOgProps {
  invite: ReferralResolveResponse;
  code: string;
  copyVariant: ReferralCopyVariant;
  baseUrl: string;
}

function InviteOgCard({ invite, code, copyVariant, baseUrl }: InviteOgProps) {
  const prices = offerPrices(invite.offer);
  const referrer = invite.referrer_first_name ?? REFERRAL_UI_COPY.unnamedFriend;
  const { og } = REFERRAL_COPY[copyVariant];

  return (
    <WallpaperCard
      baseUrl={baseUrl}
      footer={
        <span style={{ fontSize: 22, color: colors.muted }}>
          {REFERRAL_UI_COPY.ogDomain}
        </span>
      }
      aside={<GiftTicketArt prices={prices} code={code} />}
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <ReferrerFace
            name={referrer}
            picture={getOgCompatibleAvatarUrl(invite.referrer_picture)}
          />
          <span style={{ fontSize: 26, color: colors.mutedLighter }}>
            {REFERRAL_UI_COPY.landingFrom(referrer)}
          </span>
        </div>
        <div
          style={{
            fontFamily: fonts.serif,
            fontSize: 86,
            lineHeight: 1.0,
            letterSpacing: "-0.02em",
          }}
        >
          {og.title(referrer)}
        </div>
      </div>
    </WallpaperCard>
  );
}

export async function renderInviteOgImage(
  props: InviteOgProps,
): Promise<ImageResponse> {
  const prices = offerPrices(props.invite.offer);
  const referrer =
    props.invite.referrer_first_name ?? REFERRAL_UI_COPY.unnamedFriend;
  const { og } = REFERRAL_COPY[props.copyVariant];
  // Google Fonts subsets to exactly these glyphs, so every rendered string belongs here.
  const sansText = [
    REFERRAL_UI_COPY.landingFrom(referrer),
    REFERRAL_UI_COPY.landingPeriod(prices),
    REFERRAL_UI_COPY.perMonth,
    REFERRAL_UI_COPY.ogTicketLabel,
    REFERRAL_UI_COPY.ogDomain,
    prices.intro,
    prices.regular,
    props.code.toUpperCase(),
    referrer.charAt(0).toUpperCase(),
  ].join("");
  const loaded = await loadFonts(
    `${og.title(referrer)}${prices.intro}`,
    sansText,
  );
  return new ImageResponse(<InviteOgCard {...props} />, {
    width: OG_WIDTH,
    height: OG_HEIGHT,
    fonts: loaded.length > 0 ? loaded : undefined,
  });
}
