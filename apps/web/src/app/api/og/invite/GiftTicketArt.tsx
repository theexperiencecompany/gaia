import { REFERRAL_UI_COPY } from "@/features/referrals/referralCopy";
import type { OfferPrices } from "@/features/referrals/utils/offerPrices";
import { colors, fonts } from "../lib";
import { TICKET_BOTTOM, TICKET_TOP } from "./ticketTheme";

/** The ticket outline: a rounded card with half-circle bites where the stub tears off. */
const TICKET = {
  width: 400,
  height: 480,
  radius: 36,
  notch: 22,
  tear: 344,
} as const;

function ticketPath(): string {
  const { width: w, height: h, radius: r, notch: n, tear: t } = TICKET;
  return [
    `M ${r} 0 H ${w - r} A ${r} ${r} 0 0 1 ${w} ${r}`,
    `V ${t - n} A ${n} ${n} 0 0 0 ${w} ${t + n}`,
    `V ${h - r} A ${r} ${r} 0 0 1 ${w - r} ${h} H ${r} A ${r} ${r} 0 0 1 0 ${h - r}`,
    `V ${t + n} A ${n} ${n} 0 0 0 0 ${t - n}`,
    `V ${r} A ${r} ${r} 0 0 1 ${r} 0 Z`,
  ].join(" ");
}

/** The gift ticket on the invite card: the intro price above the tear, the list price and code below. */
export function GiftTicketArt({
  prices,
  code,
}: {
  prices: OfferPrices;
  code: string;
}) {
  const { width, height, notch, tear } = TICKET;
  return (
    <div style={{ width, height, display: "flex", position: "relative" }}>
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        aria-hidden="true"
        style={{ position: "absolute", top: 0, left: 0 }}
      >
        <defs>
          <linearGradient id="ticket" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor={TICKET_TOP} />
            <stop offset="1" stopColor={TICKET_BOTTOM} />
          </linearGradient>
        </defs>
        <path d={ticketPath()} fill="url(#ticket)" />
        <path
          d={ticketPath()}
          fill="none"
          stroke="rgba(255,255,255,0.07)"
          strokeWidth={2}
        />
        <line
          x1={notch + 14}
          y1={tear}
          x2={width - notch - 14}
          y2={tear}
          stroke="rgba(161,161,170,0.45)"
          strokeWidth={2}
          strokeDasharray="8 8"
        />
      </svg>
      <div
        style={{
          position: "absolute",
          top: 0,
          left: 0,
          width,
          height: tear,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          padding: "38px 40px 34px",
        }}
      >
        <span
          style={{ fontSize: 17, letterSpacing: "0.18em", color: colors.muted }}
        >
          {REFERRAL_UI_COPY.ogTicketLabel}
        </span>
        <div style={{ display: "flex", flexDirection: "column" }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
            <span
              style={{
                fontFamily: fonts.serif,
                fontSize: 156,
                letterSpacing: "-0.01em",
                lineHeight: 1,
              }}
            >
              {prices.intro}
            </span>
            <span style={{ fontSize: 28, color: colors.mutedLight }}>
              {REFERRAL_UI_COPY.perMonth}
            </span>
          </div>
          <span
            style={{ fontSize: 24, color: colors.mutedLight, marginTop: 12 }}
          >
            {REFERRAL_UI_COPY.landingPeriod(prices)}
          </span>
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          top: tear,
          left: 0,
          width,
          height: height - tear,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          padding: "0 40px",
        }}
      >
        <span
          style={{
            fontSize: 22,
            color: colors.muted,
            textDecoration: "line-through",
          }}
        >
          {`${prices.regular}${REFERRAL_UI_COPY.perMonth}`}
        </span>
        <span
          style={{ fontSize: 17, letterSpacing: "0.12em", color: colors.muted }}
        >
          {code.toUpperCase()}
        </span>
      </div>
    </div>
  );
}
