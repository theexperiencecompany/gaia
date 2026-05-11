// biome-ignore-all lint/a11y/noSvgWithoutTitle: decorative status-bar icons
"use client";

import type React from "react";
import { cn } from "@/lib/utils";

export interface IPhoneMockupProps {
  /** Status bar time, e.g. "9:41" */
  time?: string;
  /** Screen background color (CSS color) */
  screenBackground?: string;
  /** Tint the status bar icons/time. "auto" picks based on screen background brightness */
  statusBarTone?: "auto" | "light" | "dark";
  /** Hide the status bar entirely (useful for full-screen apps that draw their own) */
  hideStatusBar?: boolean;
  /** Show a 5px home-indicator bar at the bottom */
  homeIndicator?: boolean;
  /** Tint the home indicator. "auto" picks based on screen background brightness */
  homeIndicatorTone?: "auto" | "light" | "dark";
  /** Outer chassis className overrides */
  className?: string;
  /** Inner screen className overrides */
  screenClassName?: string;
  children?: React.ReactNode;
}

/**
 * Realistic iPhone (Pro) mockup with Dynamic Island, side buttons,
 * status bar and home indicator. 390 × 815 chassis, 10 px bezel,
 * 56 / 46 px corner radii, 120 × 37 Dynamic Island.
 */
export function IPhoneMockup({
  time = "9:41",
  screenBackground,
  statusBarTone = "auto",
  hideStatusBar = false,
  homeIndicator = true,
  homeIndicatorTone = "auto",
  className,
  screenClassName,
  children,
}: IPhoneMockupProps) {
  const resolvedTone =
    statusBarTone === "auto"
      ? isDarkColor(screenBackground)
        ? "light"
        : "dark"
      : statusBarTone;

  const resolvedHomeTone =
    homeIndicatorTone === "auto"
      ? isDarkColor(screenBackground)
        ? "light"
        : "dark"
      : homeIndicatorTone;

  const fg = resolvedTone === "light" ? "#ffffff" : "#000000";

  return (
    <div
      className={cn(
        "relative inline-block rounded-[56px] bg-black p-[10px]",
        "shadow-[0_50px_100px_-20px_rgba(0,0,0,0.35),0_30px_60px_-30px_rgba(0,0,0,0.4),inset_0_0_0_1px_rgba(255,255,255,0.04)]",
        className,
      )}
      style={{
        width: 390,
        maxWidth: "100%",
        aspectRatio: "390 / 815",
      }}
      aria-label="iPhone mockup"
      role="img"
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 rounded-[56px]"
        style={{
          background:
            "linear-gradient(135deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0) 30%, rgba(255,255,255,0) 70%, rgba(255,255,255,0.04) 100%)",
        }}
      />

      <SideButtons />

      <div
        className={cn(
          "relative flex h-full w-full flex-col overflow-hidden rounded-[46px]",
          screenClassName,
        )}
        style={{
          background: screenBackground ?? "#ffffff",
        }}
      >
        {/* Dynamic Island */}
        <div
          aria-hidden="true"
          className="absolute top-[12px] left-1/2 z-20 -translate-x-1/2 rounded-full bg-black"
          style={{
            width: 96,
            height: 28,
            boxShadow:
              "inset 0 0 0 0.5px rgba(255,255,255,0.06), 0 1px 2px rgba(0,0,0,0.3)",
          }}
        >
          <div
            className="absolute top-1/2 right-[9px] -translate-y-1/2 rounded-full"
            style={{
              width: 8,
              height: 8,
              background:
                "radial-gradient(circle at 30% 30%, #2a2f3a 0%, #0b0e14 60%, #000 100%)",
              boxShadow: "inset 0 0 0 0.5px rgba(255,255,255,0.08)",
            }}
          >
            <span
              className="absolute top-[2px] left-[2px] rounded-full"
              style={{
                width: 2,
                height: 2,
                background: "rgba(120,200,255,0.55)",
              }}
            />
          </div>
        </div>

        {!hideStatusBar && (
          <div
            className="relative z-10 flex shrink-0 items-center justify-between"
            style={{ height: 54, padding: "0 26px" }}
          >
            <span
              style={{
                width: 80,
                fontSize: 17,
                lineHeight: 1,
                fontWeight: 600,
                letterSpacing: "-0.01em",
                color: fg,
                fontFamily:
                  '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", Helvetica, Arial, sans-serif',
              }}
            >
              {time}
            </span>
            <div
              className="flex items-center justify-end"
              style={{ width: 80, gap: 5, color: fg }}
            >
              <CellularIcon color={fg} />
              <WifiIcon color={fg} />
              <BatteryIcon color={fg} />
            </div>
          </div>
        )}

        <div
          className="relative z-0 flex min-h-0 flex-1 flex-col"
          style={{
            paddingBottom: homeIndicator ? 22 : 0,
          }}
        >
          {children}
        </div>

        {homeIndicator && (
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-[8px] left-1/2 z-30 -translate-x-1/2 rounded-full"
            style={{
              width: 134,
              height: 5,
              background:
                resolvedHomeTone === "light"
                  ? "rgba(255,255,255,0.85)"
                  : "rgba(0,0,0,0.85)",
            }}
          />
        )}
      </div>
    </div>
  );
}

function SideButtons() {
  return (
    <>
      <span
        aria-hidden="true"
        className="absolute rounded-l-[2px]"
        style={{
          left: -2,
          top: 105,
          width: 4,
          height: 32,
          background: "linear-gradient(90deg, #1a1d22 0%, #0a0c10 100%)",
        }}
      />
      <span
        aria-hidden="true"
        className="absolute rounded-l-[2px]"
        style={{
          left: -2,
          top: 175,
          width: 4,
          height: 60,
          background: "linear-gradient(90deg, #1a1d22 0%, #0a0c10 100%)",
        }}
      />
      <span
        aria-hidden="true"
        className="absolute rounded-l-[2px]"
        style={{
          left: -2,
          top: 250,
          width: 4,
          height: 60,
          background: "linear-gradient(90deg, #1a1d22 0%, #0a0c10 100%)",
        }}
      />
      <span
        aria-hidden="true"
        className="absolute rounded-r-[2px]"
        style={{
          right: -2,
          top: 200,
          width: 4,
          height: 96,
          background: "linear-gradient(270deg, #1a1d22 0%, #0a0c10 100%)",
        }}
      />
    </>
  );
}

/* ------------------------------------------------------------------
 * Status bar icons extracted from Frame 2.svg.
 * Paths preserved verbatim (translated to local viewBoxes) so the
 * curvature, corner radii and proportions match pixel-for-pixel.
 * ------------------------------------------------------------------ */

function CellularIcon({ color }: { color: string }) {
  return (
    <svg
      width="18"
      height="12"
      viewBox="185 211 139 88"
      fill={color}
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M323.798 219.308C323.798 214.759 320.366 211.072 316.133 211.072H308.468C304.235 211.072 300.803 214.759 300.803 219.308V290.692C300.803 295.241 304.235 298.928 308.468 298.928H316.133C320.366 298.928 323.798 295.241 323.798 290.692V219.308ZM270.378 228.643H278.042C282.276 228.643 285.707 232.419 285.707 237.077V290.494C285.707 295.152 282.276 298.928 278.042 298.928H270.378C266.144 298.928 262.713 295.152 262.713 290.494V237.077C262.713 232.419 266.144 228.643 270.378 228.643ZM239.25 247.679H231.585C227.352 247.679 223.921 251.503 223.921 256.22V290.387C223.921 295.104 227.352 298.928 231.585 298.928H239.25C243.483 298.928 246.915 295.104 246.915 290.387V256.22C246.915 251.503 243.483 247.679 239.25 247.679ZM201.16 265.25H193.495C189.262 265.25 185.83 269.02 185.83 273.67V290.509C185.83 295.159 189.262 298.928 193.495 298.928H201.16C205.393 298.928 208.825 295.159 208.825 290.509V273.67C208.825 269.02 205.393 265.25 201.16 265.25Z"
      />
    </svg>
  );
}

function WifiIcon({ color }: { color: string }) {
  // viewBox covers the full curvature of the outer wave (Bezier apex ≈ y 210.7)
  // so the top of the largest arc isn't clipped.
  return (
    <svg
      width="17"
      height="12"
      viewBox="370 207 132 95"
      fill={color}
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M435.69 228.428C453.562 228.429 470.75 235.054 483.703 246.936C484.678 247.853 486.237 247.842 487.198 246.91L496.521 237.831C497.008 237.359 497.279 236.718 497.275 236.052C497.271 235.386 496.992 234.75 496.5 234.282C462.504 202.847 408.871 202.847 374.875 234.282C374.382 234.749 374.103 235.386 374.098 236.052C374.094 236.718 374.364 237.358 374.851 237.831L384.177 246.91C385.137 247.843 386.697 247.855 387.672 246.936C400.626 235.054 417.816 228.428 435.69 228.428ZM435.666 258.754C445.419 258.753 454.825 262.431 462.054 269.071C463.032 270.014 464.573 269.993 465.526 269.025L474.776 259.545C475.263 259.048 475.533 258.373 475.526 257.672C475.519 256.971 475.236 256.302 474.739 255.815C452.723 235.042 418.628 235.042 396.612 255.815C396.114 256.302 395.831 256.971 395.824 257.673C395.818 258.374 396.089 259.048 396.577 259.545L405.824 269.025C406.778 269.993 408.318 270.014 409.296 269.071C416.521 262.435 425.919 258.758 435.666 258.754ZM453.806 278.828C453.82 279.585 453.553 280.315 453.07 280.845L437.429 298.484C436.97 299.003 436.345 299.294 435.693 299.294C435.041 299.294 434.415 299.003 433.957 298.484L418.313 280.845C417.83 280.314 417.564 279.584 417.578 278.827C417.593 278.07 417.886 277.353 418.389 276.846C428.378 267.404 443.008 267.404 452.997 276.846C453.499 277.354 453.792 278.071 453.806 278.828Z"
      />
    </svg>
  );
}

function BatteryIcon({
  color,
  percent = 80,
}: {
  color: string;
  percent?: number;
}) {
  const clamped = Math.max(0, Math.min(100, percent));
  // Geometry preserved from Frame 2.svg, but drawn as stroke-only so the
  // status bar background shows through (no grey wash).
  return (
    <svg
      width="27"
      height="13"
      viewBox="547 204 197 101"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      {/* Outer body — outline only */}
      <rect
        x={550}
        y={207.2}
        width={174.4}
        height={95}
        rx={28.7432}
        ry={28.7432}
        fill="none"
        stroke={color}
        strokeOpacity="0.45"
        strokeWidth={5}
      />
      {/* Battery tip */}
      <rect
        x={729}
        y={243.9}
        width={11.5}
        height={21.6}
        rx={4}
        ry={4}
        fill={color}
        fillOpacity="0.45"
      />
      {/* Fill bar */}
      <rect
        x={559}
        y={216}
        width={156 * (clamped / 100)}
        height={78}
        rx={20}
        ry={20}
        fill={color}
      />
    </svg>
  );
}

function isDarkColor(color?: string): boolean {
  if (!color) return false;
  const c = color.trim().toLowerCase();
  if (c === "#000" || c === "#000000" || c === "black") return true;
  const hex = c.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/);
  if (hex) {
    let h = hex[1];
    if (h.length === 3)
      h = h
        .split("")
        .map((ch) => ch + ch)
        .join("");
    const r = Number.parseInt(h.slice(0, 2), 16);
    const g = Number.parseInt(h.slice(2, 4), 16);
    const b = Number.parseInt(h.slice(4, 6), 16);
    const yiq = (r * 299 + g * 587 + b * 114) / 1000;
    return yiq < 128;
  }
  const rgb = c.match(/rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/);
  if (rgb) {
    const r = Number.parseInt(rgb[1], 10);
    const g = Number.parseInt(rgb[2], 10);
    const b = Number.parseInt(rgb[3], 10);
    const yiq = (r * 299 + g * 587 + b * 114) / 1000;
    return yiq < 128;
  }
  return false;
}
