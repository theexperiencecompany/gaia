"use client";

import { useId } from "react";
import { FILE_TYPE_STYLES } from "@/features/chat/components/files/fileTypeConfig";

const DOCUMENT_PATH = [
  "M176,109 C174.896,109 174,108.104 174,107 L174,103 L180,109 L176,109 L176,109 Z",
  "M174,101 L174,101.028 C173.872,101.028 160,101 160,101 C157.791,101 156,102.791 156,105 L156,129 C156,131.209 157.791,133 160,133 L178,133 C180.209,133 182,131.209 182,129 L182,111 L182,109 L174,101 L174,101 Z",
].join(" ");

// The document sits inside a 32x32 viewBox (x: 9.375%..90.625%, full height),
// centered horizontally. Content overlays that same region.
const DOC_LEFT = 9.375;
const DOC_WIDTH = 81.25;

interface FileTypeIconProps {
  readonly extension: string;
  readonly size?: number;
}

export function FileTypeIcon({ extension, size = 44 }: FileTypeIconProps) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const { from, to, Glyph } =
    FILE_TYPE_STYLES[extension.toLowerCase()] ?? FILE_TYPE_STYLES.file;
  const gradientId = `filetype-gradient-${uid}`;
  const clipId = `filetype-clip-${uid}`;
  const outlineGradientId = `filetype-outline-${uid}`;

  return (
    <div
      className="group/filetype relative shrink-0"
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${extension.toUpperCase()} file`}
    >
      <div
        className="pointer-events-none absolute inset-0 scale-[0.92] -rotate-[10deg] -translate-x-[17%] translate-y-[3%] transition-transform duration-200 ease-out group-hover/filetype:-rotate-[15deg] group-hover/filetype:-translate-x-[24%] group-hover/filetype:translate-y-[7%]"
        style={{ opacity: 0.5 }}
        aria-hidden="true"
      >
        <svg className="h-full w-full" viewBox="-3 0 32 32" aria-hidden="true">
          <path
            d={DOCUMENT_PATH}
            fill="#C7CDD6"
            fillRule="evenodd"
            transform="translate(-156 -101)"
          />
        </svg>
      </div>
      <div className="absolute inset-0 rotate-[9deg] transition-transform duration-200 ease-out group-hover/filetype:rotate-[14deg]">
        <svg className="absolute inset-0 h-full w-full" viewBox="-3 0 32 32">
          <title>{`${extension.toUpperCase()} file`}</title>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={from} />
              <stop offset="1" stopColor={to} />
            </linearGradient>
            <linearGradient id={outlineGradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor={to} />
              <stop offset="1" stopColor={from} />
            </linearGradient>
            <clipPath id={clipId}>
              <path d={DOCUMENT_PATH} transform="translate(-156 -101)" />
            </clipPath>
          </defs>
          <g clipPath={`url(#${clipId})`}>
            <path
              d={DOCUMENT_PATH}
              fill={`url(#${gradientId})`}
              fillRule="evenodd"
              transform="translate(-156 -101)"
            />
            <path
              d={DOCUMENT_PATH}
              fill="none"
              stroke={`url(#${outlineGradientId})`}
              strokeWidth="1.2"
              transform="translate(-156 -101)"
            />
          </g>
        </svg>
        <div
          className="pointer-events-none absolute flex flex-col items-center"
          style={{
            left: `${DOC_LEFT}%`,
            width: `${DOC_WIDTH}%`,
            top: 0,
            height: "100%",
            padding: `${size * 0.12}px ${size * 0.01}px ${size * 0.16}px`,
          }}
        >
          <div className="flex flex-1 items-center justify-center">
            <Glyph size={Math.round(size * 0.34)} color="#FFFFFF" />
          </div>
          <div
            className="font-semibold uppercase tracking-wider text-white"
            style={{
              fontSize: Math.max(7, Math.round(size * 0.15)),
              lineHeight: 1,
            }}
          >
            {extension.toUpperCase()}
          </div>
        </div>
      </div>
    </div>
  );
}
