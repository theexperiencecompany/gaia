import type React from "react";

export type StatusGlyphKind =
  | "proposed" // amber ring + core dot — waiting on your word
  | "blocked" // amber ring, hollow — waiting on an answer
  | "queued" // blue ring, quarter arc
  | "done" // filled emerald circle + check
  | "failed" // red ring + core dot — needs attention
  | "suggested"; // violet dashed ring — an offer, not yet real work

interface StatusGlyphProps {
  kind: StatusGlyphKind;
  /** Rendered square size in px; marks scale from one 14px grid. */
  size?: number;
  className?: string;
}

/**
 * Linear-style status indicators shared by the Today dashboard and the todos
 * surface — one glyph language product-wide. Bespoke marks (dashed ring,
 * ring-dot, arc) no icon library carries; status is encoded in form, not just
 * color. Running states use HeroUI <Spinner>, never these.
 */
export const StatusGlyph: React.FC<StatusGlyphProps> = ({
  kind,
  size = 22,
  className,
}) => {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 14 14"
      className={className}
      aria-hidden="true"
    >
      {kind === "proposed" && (
        <>
          <circle
            cx="7"
            cy="7"
            r="5.5"
            fill="none"
            stroke="#fbbf24"
            strokeWidth="1.5"
          />
          <circle cx="7" cy="7" r="2.4" fill="#fbbf24" />
        </>
      )}
      {kind === "blocked" && (
        <>
          <circle
            cx="7"
            cy="7"
            r="5.5"
            fill="none"
            stroke="#fbbf24"
            strokeWidth="1.5"
          />
          <circle
            cx="7"
            cy="7"
            r="2.4"
            fill="none"
            stroke="#fbbf24"
            strokeWidth="1.2"
          />
        </>
      )}
      {kind === "queued" && (
        <>
          <circle
            cx="7"
            cy="7"
            r="5.5"
            fill="none"
            stroke="#60a5fa"
            strokeWidth="1.5"
            opacity="0.35"
          />
          <path
            d="M7 1.5 a5.5 5.5 0 0 1 5.5 5.5"
            fill="none"
            stroke="#60a5fa"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </>
      )}
      {kind === "done" && (
        <>
          <circle cx="7" cy="7" r="6" fill="#34d399" />
          <path
            d="M4.4 7.2 6.2 9 9.7 5.4"
            fill="none"
            stroke="#0a0a0a"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      )}
      {kind === "failed" && (
        <>
          <circle
            cx="7"
            cy="7"
            r="5.5"
            fill="none"
            stroke="#f87171"
            strokeWidth="1.5"
          />
          <circle cx="7" cy="7" r="2.4" fill="#f87171" />
        </>
      )}
      {kind === "suggested" && (
        <circle
          cx="7"
          cy="7"
          r="5.5"
          fill="none"
          stroke="#a78bfa"
          strokeWidth="1.5"
          strokeDasharray="2.4 2.3"
        />
      )}
    </svg>
  );
};
