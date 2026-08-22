import type { UsageActivity } from "@shared/types";
import { formatCompactNumber } from "@shared/utils";
import { buildTweetText, openTweetIntent } from "./shareTweet";

/** Everything the card needs from the badge tier (see TIERS in UsageHeatmap). */
export interface ShareTierArt {
  label: string;
  src: string;
  filter: string;
}

const WIDTH = 1200;
const HEIGHT = 630;
const BG = "#111113";
const MARGIN = 80;

/** Render the activity share card (medal + stats + year heatmap) to a PNG and
 * hand it to the native share sheet; falls back to downloading the image and
 * opening the X intent when file sharing isn't available. */
export async function shareActivityCard(
  activity: UsageActivity,
  tier: ShareTierArt,
  cellColor: (count: number | null, max: number) => string,
): Promise<void> {
  const canvas = document.createElement("canvas");
  canvas.width = WIDTH;
  canvas.height = HEIGHT;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");

  ctx.fillStyle = BG;
  ctx.fillRect(0, 0, WIDTH, HEIGHT);

  // Brand, top-left
  ctx.fillStyle = "#00bbff";
  ctx.font = "600 30px Inter, system-ui, sans-serif";
  ctx.fillText("GAIA", MARGIN, 76);

  // Top row: medal on the left, text block vertically centered beside it
  const medal = new Image();
  medal.src = tier.src;
  await medal.decode();
  ctx.save();
  if (tier.filter) ctx.filter = tier.filter;
  ctx.drawImage(medal, MARGIN, 110, 240, 240);
  ctx.restore();

  const textX = MARGIN + 240 + 48;
  ctx.fillStyle = "#ffffff";
  ctx.font = "600 64px Inter, system-ui, sans-serif";
  ctx.fillText(tier.label, textX, 210);
  ctx.fillStyle = "#a1a1aa";
  ctx.font = "400 28px Inter, system-ui, sans-serif";
  ctx.fillText("of GAIA users by activity", textX, 254);
  ctx.fillStyle = "#71717a";
  ctx.font = "400 26px Inter, system-ui, sans-serif";
  ctx.fillText(
    `${formatCompactNumber(activity.total)} actions · ${activity.streak}-day streak`,
    textX,
    308,
  );

  // Bottom band: the year heatmap spanning the full content width. Cell size is
  // derived from the available width so all ~53 weeks always fit exactly.
  const weeks = Math.ceil(activity.days.length / 7);
  const contentWidth = WIDTH - MARGIN * 2;
  const step = Math.floor(contentWidth / weeks); // cell + gap
  const cell = step - 4;
  const gridWidth = weeks * step - 4;
  const originX = MARGIN + Math.floor((contentWidth - gridWidth) / 2);
  const originY = 408;
  const max = Math.max(1, ...activity.days.map((d) => d.count));
  activity.days.forEach((day, i) => {
    const week = Math.floor(i / 7);
    const dow = i % 7;
    const color = cellColor(day.count, max);
    ctx.fillStyle = color === "transparent" ? BG : color;
    ctx.beginPath();
    ctx.roundRect(originX + week * step, originY + dow * step, cell, cell, 3);
    ctx.fill();
  });

  ctx.fillStyle = "#52525b";
  ctx.font = "400 22px Inter, system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText("heygaia.io", WIDTH - MARGIN, HEIGHT - 36);
  ctx.textAlign = "left";

  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("canvas.toBlob failed"))),
      "image/png",
    ),
  );
  const text = buildTweetText(tier.label, activity.streak);
  const file = new File([blob], "gaia-activity.png", { type: "image/png" });

  if (navigator.canShare?.({ files: [file] })) {
    await navigator.share({ files: [file], text });
    return;
  }

  // Fallback: save the image locally, then open the X intent so the user can
  // attach it — the tweet intent API itself cannot carry an image.
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "gaia-activity.png";
  anchor.click();
  URL.revokeObjectURL(url);
  openTweetIntent(text);
}
