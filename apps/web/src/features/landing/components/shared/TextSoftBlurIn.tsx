"use client";

import {
  type CSSProperties,
  createElement,
  type ReactNode,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import { cn } from "@/lib/utils";

type AsTag = "h1" | "h2" | "h3" | "p" | "div" | "span";

interface TextSoftBlurInProps {
  text: string;
  as?: AsTag;
  className?: string;
  startDelay?: number;
  charStagger?: number;
  duration?: number;
  blur?: number;
  yOffset?: number;
  splitBy?: "char" | "word";
  immediate?: boolean;
  gradient?: string;
  threshold?: number;
}

const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

/** Style object that allows the `--sbi-*` custom properties used by the keyframe. */
type AnimStyle = CSSProperties & Record<`--${string}`, string>;

function splitText(text: string, splitBy: "char" | "word"): string[] {
  if (splitBy === "word") {
    const words = text.split(" ");
    return words.map((w, i) => (i < words.length - 1 ? `${w} ` : w));
  }
  return Array.from(text);
}

// Each char carries its global index (`gid`) so the render can key on a stable
// identity instead of the per-word map index (noArrayIndexKey / Sonar S6479).
type CharCell = { ch: string; gid: number };

function groupIntoWords(
  chars: string[],
): { chars: CharCell[]; start: number; isSpace: boolean }[] {
  const groups: { chars: CharCell[]; start: number; isSpace: boolean }[] = [];
  let word: CharCell[] = [];
  let wordStart = 0;

  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];
    if (ch === " ") {
      if (word.length > 0) {
        groups.push({ chars: word, start: wordStart, isSpace: false });
        word = [];
      }
      groups.push({ chars: [{ ch, gid: i }], start: i, isSpace: true });
    } else {
      if (word.length === 0) wordStart = i;
      word.push({ ch, gid: i });
    }
  }
  if (word.length > 0) {
    groups.push({ chars: word, start: wordStart, isSpace: false });
  }
  return groups;
}

function gradientCss(gradient?: string): CSSProperties | undefined {
  return gradient
    ? {
        backgroundImage: gradient,
        WebkitBackgroundClip: "text",
        WebkitTextFillColor: "transparent",
        backgroundClip: "text",
        color: "transparent",
      }
    : undefined;
}

const GRADIENT_INHERIT: CSSProperties = {
  backgroundImage: "inherit",
  WebkitBackgroundClip: "inherit",
  WebkitTextFillColor: "inherit",
  backgroundClip: "inherit",
};

/** Shared inner renderer for both immediate and scroll-triggered text variants. */
function TextInner({
  text,
  parts,
  splitBy,
  gradient,
  buildCharStyle,
  innerRef,
  baseId,
}: Readonly<{
  text: string;
  parts: string[];
  splitBy: "char" | "word";
  gradient?: string;
  buildCharStyle: (idx: number) => CSSProperties;
  innerRef?: React.RefObject<HTMLSpanElement | null>;
  baseId?: string;
}>) {
  // The per-character spans are decorative (aria-hidden); a visually-hidden copy
  // of the full string is the real accessible text. This gives the wrapping
  // element an accessible name via its content, instead of an `aria-label` —
  // which ARIA prohibits on generic <span>/<div> elements that have no role.
  if (splitBy === "char") {
    return (
      <>
        <span className="sr-only">{text}</span>
        <span ref={innerRef} aria-hidden="true" style={gradientCss(gradient)}>
          {groupIntoWords(parts).map(({ chars, start, isSpace }) => (
            <span
              key={start}
              style={{
                display: isSpace ? "inline" : "inline-block",
                ...(gradient && !isSpace ? GRADIENT_INHERIT : null),
              }}
            >
              {chars.map(({ ch, gid }) => (
                <span
                  key={gid}
                  className="sbi-anim"
                  style={buildCharStyle(gid)}
                >
                  {ch}
                </span>
              ))}
            </span>
          ))}
        </span>
      </>
    );
  }

  return (
    <>
      <span className="sr-only">{text}</span>
      <span
        ref={innerRef}
        aria-hidden="true"
        className="inline-block"
        style={gradientCss(gradient)}
      >
        {parts.map((part, i) => (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: stable id + index
            key={baseId ? `${baseId}-${i}` : i}
            className="sbi-anim"
            style={buildCharStyle(i)}
          >
            {part}
          </span>
        ))}
      </span>
    </>
  );
}

/**
 * Above-the-fold variant: the blur-in runs as a CSS `@keyframes` animation that
 * auto-plays straight from the server-rendered HTML. It has no state, effects,
 * or IntersectionObserver, so the text paints and animates without waiting for
 * React hydration — which is what keeps it off the LCP critical path.
 */
function TextSoftBlurInImmediate({
  text,
  as = "div",
  className,
  startDelay = 0.03,
  charStagger = 0.015,
  duration = 0.5,
  blur = 12,
  yOffset = 16,
  splitBy = "char",
  gradient,
}: TextSoftBlurInProps) {
  const parts = splitText(text, splitBy);

  const buildCharStyle = (globalIdx: number): AnimStyle => {
    const delay = startDelay + globalIdx * charStagger;
    return {
      display: "inline-block",
      whiteSpace: "pre",
      paddingBlock: "0.12em",
      marginBlock: "-0.12em",
      paddingInline: "0.05em",
      marginInline: "-0.05em",
      animation: `gaia-soft-blur-in ${duration}s ${EASE} ${delay}s both`,
      "--sbi-blur": `${blur}px`,
      "--sbi-y": `${yOffset}px`,
      ...(gradient ? GRADIENT_INHERIT : null),
    };
  };

  return createElement(
    as,
    { className: cn(className) },
    <TextInner
      text={text}
      parts={parts}
      splitBy={splitBy}
      gradient={gradient}
      buildCharStyle={buildCharStyle}
    />,
  );
}

function useFreezeOnIntersect(
  ref: React.RefObject<HTMLElement | null>,
  threshold: number,
): boolean {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;

    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry?.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [ref, threshold]);

  return visible;
}

/** Scroll-triggered variant (below the fold): reveals on intersection. */
function TextSoftBlurInOnScroll({
  text,
  as = "div",
  className,
  startDelay = 0.03,
  charStagger = 0.015,
  duration = 0.5,
  blur = 12,
  yOffset = 16,
  splitBy = "char",
  gradient,
  threshold = 0.15,
}: TextSoftBlurInProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const isVisible = useFreezeOnIntersect(ref, threshold);
  const baseId = useId();

  const parts = useMemo(() => splitText(text, splitBy), [text, splitBy]);

  const totalAnimMs =
    (startDelay + parts.length * charStagger + duration) * 1000;
  const [animDone, setAnimDone] = useState(false);
  useEffect(() => {
    if (!isVisible) return;
    const id = window.setTimeout(() => setAnimDone(true), totalAnimMs + 50);
    return () => window.clearTimeout(id);
  }, [isVisible, totalAnimMs]);

  const buildCharStyle = (globalIdx: number): CSSProperties => {
    const delay = startDelay + globalIdx * charStagger;
    return {
      display: "inline-block",
      whiteSpace: "pre",
      paddingBlock: "0.12em",
      marginBlock: "-0.12em",
      paddingInline: "0.05em",
      marginInline: "-0.05em",
      opacity: isVisible ? 1 : 0,
      filter: isVisible ? "blur(0px)" : `blur(${blur}px)`,
      transform: isVisible ? "none" : `translateY(${yOffset}px)`,
      transition: `opacity ${duration}s ${EASE} ${delay}s, filter ${duration}s ${EASE} ${delay}s, transform ${duration}s ${EASE} ${delay}s`,
      willChange: animDone ? "auto" : "opacity, filter, transform",
      ...(gradient ? GRADIENT_INHERIT : null),
    };
  };

  return createElement(
    as,
    { className: cn(className) },
    <TextInner
      text={text}
      parts={parts}
      splitBy={splitBy}
      gradient={gradient}
      buildCharStyle={buildCharStyle}
      innerRef={ref}
      baseId={baseId}
    />,
  );
}

export function TextSoftBlurIn(props: TextSoftBlurInProps) {
  return props.immediate ? (
    <TextSoftBlurInImmediate {...props} />
  ) : (
    <TextSoftBlurInOnScroll {...props} />
  );
}

interface SoftBlurInBlockProps {
  children: ReactNode;
  as?: AsTag;
  className?: string;
  delay?: number;
  duration?: number;
  blur?: number;
  yOffset?: number;
  immediate?: boolean;
  threshold?: number;
}

function SoftBlurInBlockImmediate({
  children,
  as = "div",
  className,
  delay = 0.03,
  duration = 0.55,
  blur = 12,
  yOffset = 16,
}: SoftBlurInBlockProps) {
  const style: AnimStyle = {
    animation: `gaia-soft-blur-in ${duration}s ${EASE} ${delay}s both`,
    "--sbi-blur": `${blur}px`,
    "--sbi-y": `${yOffset}px`,
  };
  return createElement(
    as,
    { className: cn(className, "sbi-anim"), style },
    children,
  );
}

function SoftBlurInBlockOnScroll({
  children,
  as = "div",
  className,
  delay = 0.03,
  duration = 0.55,
  blur = 12,
  yOffset = 16,
  threshold = 0.15,
}: SoftBlurInBlockProps) {
  const ref = useRef<HTMLElement>(null);
  const isVisible = useFreezeOnIntersect(ref, threshold);

  const [animDone, setAnimDone] = useState(false);
  useEffect(() => {
    if (!isVisible) return;
    const id = window.setTimeout(
      () => setAnimDone(true),
      (delay + duration) * 1000 + 50,
    );
    return () => window.clearTimeout(id);
  }, [isVisible, delay, duration]);

  const style: CSSProperties = {
    opacity: isVisible ? 1 : 0,
    filter: isVisible ? "blur(0px)" : `blur(${blur}px)`,
    transform: isVisible ? "none" : `translateY(${yOffset}px)`,
    transition: `opacity ${duration}s ${EASE} ${delay}s, filter ${duration}s ${EASE} ${delay}s, transform ${duration}s ${EASE} ${delay}s`,
    willChange: animDone ? "auto" : "opacity, filter, transform",
  };

  return createElement(
    as,
    { ref, className: cn(className, "sbi-anim"), style },
    children,
  );
}

export function SoftBlurInBlock(props: SoftBlurInBlockProps) {
  return props.immediate ? (
    <SoftBlurInBlockImmediate {...props} />
  ) : (
    <SoftBlurInBlockOnScroll {...props} />
  );
}
