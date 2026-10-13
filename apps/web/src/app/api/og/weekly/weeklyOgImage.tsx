import { ImageResponse } from "next/og";
import {
  REFERRAL_UI_COPY,
  WEEKLY_STATS_COPY,
} from "@/features/referrals/referralCopy";
import { INVITE_PATH } from "@/features/referrals/utils/shareTargets";
import { formatTimeSaved } from "@/features/referrals/utils/timeSaved";
import { colors, fonts, loadFonts, OG_HEIGHT, OG_WIDTH } from "../lib";

const PAGE_BG = "#0b0b0c";
const CARD_TOP = "#2c2c31";
const CARD_BOTTOM = "#1f1f22";
const WALLPAPER = "/images/wallpapers/bands_gradient_black.png";
const WALLPAPER_OPACITY = 0.55;

export interface WeeklyOgStats {
  code: string;
  minutes: number;
  actions: number;
  runs: number;
}

interface WeeklyOgProps extends WeeklyOgStats {
  baseUrl: string;
}

function StatTile({ value, label }: { value: string; label: string }) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        padding: "26px 30px",
        borderRadius: 28,
        backgroundImage: `linear-gradient(180deg, ${CARD_TOP}, ${CARD_BOTTOM})`,
      }}
    >
      <span
        style={{
          fontFamily: fonts.serif,
          fontSize: 72,
          lineHeight: 1,
          color: colors.white,
        }}
      >
        {value}
      </span>
      <span style={{ fontSize: 22, color: colors.mutedLight }}>{label}</span>
    </div>
  );
}

function WeeklyOgCard({
  code,
  minutes,
  actions,
  runs,
  baseUrl,
}: WeeklyOgProps) {
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
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <span style={{ fontSize: 30, color: colors.mutedLighter }}>
              {WEEKLY_STATS_COPY.ogLead}
            </span>
            <span
              style={{
                fontFamily: fonts.serif,
                fontSize: 128,
                lineHeight: 1,
                letterSpacing: "-0.02em",
              }}
            >
              {formatTimeSaved(minutes)}
            </span>
            <span style={{ fontSize: 30, color: colors.mutedLighter }}>
              {WEEKLY_STATS_COPY.ogTail}
            </span>
          </div>
          <span style={{ fontSize: 22, color: colors.muted }}>
            {`${REFERRAL_UI_COPY.ogDomain}${INVITE_PATH}${code}`}
          </span>
        </div>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 20,
            width: 340,
          }}
        >
          <StatTile
            value={String(actions)}
            label={WEEKLY_STATS_COPY.actions(actions)}
          />
          <StatTile
            value={String(runs)}
            label={WEEKLY_STATS_COPY.workflowRuns(runs)}
          />
        </div>
      </div>
    </div>
  );
}

export async function renderWeeklyOgImage(
  props: WeeklyOgProps,
): Promise<ImageResponse> {
  const time = formatTimeSaved(props.minutes);
  // Google Fonts subsets to exactly these glyphs, so every rendered string belongs here.
  const sansText = [
    WEEKLY_STATS_COPY.ogLead,
    WEEKLY_STATS_COPY.ogTail,
    WEEKLY_STATS_COPY.actions(props.actions),
    WEEKLY_STATS_COPY.workflowRuns(props.runs),
    `${REFERRAL_UI_COPY.ogDomain}${INVITE_PATH}${props.code}`,
  ].join("");
  const serifText = `${time}${props.actions}${props.runs}`;
  const loaded = await loadFonts(serifText, sansText);
  return new ImageResponse(<WeeklyOgCard {...props} />, {
    width: OG_WIDTH,
    height: OG_HEIGHT,
    fonts: loaded.length > 0 ? loaded : undefined,
  });
}
