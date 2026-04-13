import { cn } from "@/lib/utils";

interface SplitTextBlurProps {
  text: string;
  className?: string;
  delay?: number;
  staggerDelay?: number;
  yOffset?: number;
  disableIntersectionObserver?: boolean;
  as?: "h1" | "h2" | "h3" | "div";
  gradient?: string;
  showGlowTextBg?: boolean;
}

/**
 * CSS-only split-text blur-in animation.
 *
 * Previously used motion/react with spring physics + intersection observer,
 * which forced the hero to wait for JS hydration to paint. Now ships zero JS —
 * renders as a Server Component, animation plays entirely in CSS via
 * @keyframes hero-word-in and per-word animation-delay.
 *
 * Visual parity: same blur(10px) → blur(0), translateY(2px) → 0, opacity 0 → 1
 * per-word stagger. Slightly smoother easing (cubic-bezier vs spring) but
 * indistinguishable to the eye at 0.6s duration.
 *
 * @param delay  Base delay before the first word starts (seconds).
 * @param staggerDelay  Extra delay per subsequent word (seconds).
 */
const SplitTextBlur = ({
  text,
  className = "",
  delay = 1,
  staggerDelay = 0.1,
  gradient = "linear-gradient(to bottom, #a3a3a3, #ffffff)",
  showGlowTextBg = false,
  as: As = "div",
}: SplitTextBlurProps) => {
  const words = text.split(" ");

  const gradientStyle = {
    "--split-gradient": gradient,
  } as React.CSSProperties;

  const renderWords = (glow: boolean) =>
    words.map((word, index) => (
      <span
        // biome-ignore lint/suspicious/noArrayIndexKey: word list is static, index stable
        key={word + index}
        className="hero-split-word font-serif p-[5px] pl-0"
        style={{
          animationDelay: `${delay + index * staggerDelay}s`,
          paddingRight: index < words.length - 1 ? "0.25em" : undefined,
          paddingBottom: "7px",
          background: glow ? undefined : "inherit",
          WebkitBackgroundClip: glow ? undefined : "inherit",
          WebkitTextFillColor: glow ? undefined : "inherit",
          backgroundClip: glow ? undefined : "inherit",
        }}
      >
        {word}
        {index < words.length - 1 ? " " : ""}
      </span>
    ));

  return (
    <div className="relative" style={gradientStyle}>
      <As
        className={`${cn(className)} z-[10]`}
        style={{
          background: "var(--split-gradient)",
          WebkitBackgroundClip: "text",
          WebkitTextFillColor: "transparent",
          backgroundClip: "text",
        }}
      >
        {renderWords(false)}
      </As>
      {showGlowTextBg && (
        <div
          className={`${cn(className)} text-white blur-md absolute top-0 z-[-1]`}
          aria-hidden
        >
          {renderWords(true)}
        </div>
      )}
    </div>
  );
};

export { SplitTextBlur };
