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
import { GiftTicketArt } from "./GiftTicketArt";
import { ReferrerFace } from "./ReferrerFace";

const PAGE_BG = "#0b0b0c";
const WALLPAPER = "/images/wallpapers/bands_gradient_black.png";
const WALLPAPER_OPACITY = 0.55;

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
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        position: "relative",
        backgroundColor: PAGE_BG,
        fontFamily: fonts.sans,
        color: colors.white,
      }}
    >
      {/* biome-ignore lint/performance/noImgElement: Satori renders plain img, next/image does not exist here. */}
      <img
        src={`${baseUrl}${WALLPAPER}`}
        alt=""
        width={OG_WIDTH}
        height={OG_HEIGHT}
        style={{
          position: "absolute",
          inset: 0,
          width: OG_WIDTH,
          height: OG_HEIGHT,
          objectFit: "cover",
          opacity: WALLPAPER_OPACITY,
        }}
      />
      <div
        style={{
          display: "flex",
          flex: 1,
          alignItems: "center",
          padding: "60px 72px",
          gap: 64,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            justifyContent: "space-between",
            flex: 1,
            height: "100%",
          }}
        >
          {/* biome-ignore lint/performance/noImgElement: Satori renders plain img, next/image does not exist here. */}
          <img
            src={`${baseUrl}/brand/gaia_wordmark_white.png`}
            alt="GAIA"
            height={32}
            style={{
              height: 32,
              objectFit: "contain",
              alignSelf: "flex-start",
            }}
          />
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
          <span style={{ fontSize: 22, color: colors.muted }}>
            {REFERRAL_UI_COPY.ogDomain}
          </span>
        </div>
        <GiftTicketArt prices={prices} code={code} />
      </div>
    </div>
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
