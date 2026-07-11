import Image from "next/image";

/**
 * Static iPhone device frame for blog demo screenshots — a web port of the
 * Keyloom PhoneFrame composition (same proportions: 760×1560 design frame,
 * dynamic island, side buttons, home indicator) without the Remotion runtime.
 *
 * Used by MarkdownWrapper via the alt-text convention:
 *   ![iphone: GAIA replying on WhatsApp](/images/blog/whatsapp-demo.png)
 */

const DESIGN_W = 760;
const DESIGN_H = 1560;

interface IPhoneFrameProps {
  src: string;
  alt: string;
  /** Rendered device width in px (height follows the design aspect). */
  width?: number;
  caption?: string;
}

export function IPhoneFrame({
  src,
  alt,
  width = 320,
  caption,
}: IPhoneFrameProps) {
  const s = width / DESIGN_W;
  const height = DESIGN_H * s;
  const bezel = 18 * s;
  const frameRadius = 96 * s;
  const screenRadius = 78 * s;

  return (
    <figure className="mx-auto my-10 flex w-fit flex-col items-center gap-3">
      <div
        style={{
          width,
          height,
          background:
            "linear-gradient(150deg, #2a2a2e 0%, #0f0f12 50%, #1a1a1d 100%)",
          borderRadius: frameRadius,
          padding: bezel,
          boxShadow:
            "0 30px 70px rgba(0,0,0,0.45), 0 0 0 1px rgba(255,255,255,0.06), inset 0 0 0 1px rgba(255,255,255,0.05)",
          position: "relative",
        }}
      >
        {/* Side buttons */}
        <SideButton side="left" top={260 * s} length={140 * s} />
        <SideButton side="left" top={420 * s} length={86 * s} />
        <SideButton side="left" top={520 * s} length={86 * s} />
        <SideButton side="right" top={340 * s} length={170 * s} />

        <div
          style={{
            width: "100%",
            height: "100%",
            background: "#000",
            borderRadius: screenRadius,
            overflow: "hidden",
            position: "relative",
          }}
        >
          <Image
            src={src}
            alt={alt}
            fill
            sizes={`${width}px`}
            className="object-cover"
          />

          {/* Dynamic island */}
          <div
            style={{
              position: "absolute",
              top: 22 * s,
              left: "50%",
              transform: "translateX(-50%)",
              width: 240 * s,
              height: 56 * s,
              background: "#000",
              borderRadius: 999,
              boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.04)",
            }}
          />

          {/* Home indicator */}
          <div
            style={{
              position: "absolute",
              bottom: 14 * s,
              left: "50%",
              transform: "translateX(-50%)",
              width: 270 * s,
              height: Math.max(6 * s, 2),
              background: "rgba(255,255,255,0.55)",
              borderRadius: 999,
              mixBlendMode: "exclusion",
            }}
          />
        </div>
      </div>
      {caption ? (
        <figcaption className="max-w-xs text-center text-sm text-zinc-500">
          {caption}
        </figcaption>
      ) : null}
    </figure>
  );
}

function SideButton({
  side,
  top,
  length,
}: {
  side: "left" | "right";
  top: number;
  length: number;
}) {
  return (
    <div
      style={{
        position: "absolute",
        top,
        [side]: -1.5,
        width: 2.5,
        height: length,
        background:
          "linear-gradient(90deg, #1a1a1c 0%, #3a3a3e 50%, #1a1a1c 100%)",
        borderRadius: 2,
      }}
    />
  );
}
