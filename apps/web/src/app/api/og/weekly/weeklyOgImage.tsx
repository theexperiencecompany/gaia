import { ImageResponse } from "next/og";
import {
  REFERRAL_UI_COPY,
  WEEKLY_STATS_COPY,
} from "@/features/referrals/referralCopy";
import { INVITE_PATH } from "@/features/referrals/utils/shareTargets";
import { formatTimeSaved } from "@/features/referrals/utils/timeSaved";
import { colors, fonts, loadFonts, OG_HEIGHT, OG_WIDTH } from "../lib";
import { CARD_BOTTOM, CARD_TOP, WallpaperCard } from "../wallpaperCard";

export interface WeeklyOgStats {
  code: string;
  minutes: number;
  actions: number;
  runs: number;
}

interface StatTileProps {
  value: string;
  label: string;
}

function StatTile({ value, label }: StatTileProps) {
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

interface WeeklyOgProps extends WeeklyOgStats {
  baseUrl: string;
}

function WeeklyOgCard({
  code,
  minutes,
  actions,
  runs,
  baseUrl,
}: WeeklyOgProps) {
  return (
    <WallpaperCard
      baseUrl={baseUrl}
      footer={
        <span style={{ fontSize: 22, color: colors.muted }}>
          {`${REFERRAL_UI_COPY.ogDomain}${INVITE_PATH}${code}`}
        </span>
      }
      aside={
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
      }
    >
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
    </WallpaperCard>
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
