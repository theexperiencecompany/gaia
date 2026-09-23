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

/** Custom properties consumed by the `.sbi-*` classes in globals.css. */
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

interface CharTiming {
  startDelay: number;
  charStagger: number;
  duration: number;
  blur: number;
  yOffset: number;
}

/** Reveal state for the scroll-triggered variant; absent in immediate mode. */
interface CharReveal {
  isVisible: boolean;
  animDone: boolean;
}

/**
 * One animated character/word. The `style` holds only `--sbi-*` custom
 * properties (the CSS-var bridge); the `.sbi-*` classes in globals.css turn
 * them into animation/transition/opacity/filter/transform.
 */
function CharSpan({
  index,
  className,
  timing,
  reveal,
  children,
}: Readonly<{
  index: number;
  className?: string;
  timing: CharTiming;
  reveal?: CharReveal;
  children: ReactNode;
}>) {
  const delay = timing.startDelay + index * timing.charStagger;
  const isVisible = !reveal || reveal.isVisible;
  let filter = "none";
  if (reveal) {
    filter = isVisible ? "blur(0px)" : `blur(${timing.blur}px)`;
  }
  let transform = "none";
  if (reveal && !isVisible) {
    transform = `translateY(${timing.yOffset}px)`;
  }
  const willChange =
    reveal && !reveal.animDone ? "opacity, filter, transform" : "auto";
  return (
    <span
      className={className}
      style={
        {
          "--sbi-delay": `${delay}s`,
          "--sbi-duration": `${timing.duration}s`,
          "--sbi-blur": `${timing.blur}px`,
          "--sbi-y": `${timing.yOffset}px`,
          "--sbi-opacity": isVisible ? "1" : "0",
          "--sbi-filter": filter,
          "--sbi-transform": transform,
          "--sbi-will-change": willChange,
        } as AnimStyle
      }
    >
      {children}
    </span>
  );
}

/** Shared inner renderer for both immediate and scroll-triggered text variants. */
function TextInner({
  text,
  parts,
  splitBy,
  gradient,
  charClassName,
  timing,
  reveal,
  innerRef,
  baseId,
}: Readonly<{
  text: string;
  parts: string[];
  splitBy: "char" | "word";
  gradient?: string;
  charClassName: string;
  timing: CharTiming;
  reveal?: CharReveal;
  innerRef?: React.RefObject<HTMLSpanElement | null>;
  baseId?: string;
}>) {
  const charGradientClass = gradient ? "sbi-gradient-inherit" : undefined;
  // The per-character spans are decorative (aria-hidden); a visually-hidden
  // copy of the full string is the real accessible text — ARIA prohibits
  // `aria-label` on generic <span>/<div> elements with no role.
  if (splitBy === "char") {
    return (
      <>
        <span className="sr-only">{text}</span>
        <span
          ref={innerRef}
          aria-hidden="true"
          className={gradient ? "sbi-gradient" : undefined}
          style={
            gradient ? ({ "--sbi-gradient": gradient } as AnimStyle) : undefined
          }
        >
          {groupIntoWords(parts).map(({ chars, start, isSpace }) => (
            <span
              key={start}
              className={cn(
                isSpace ? "inline" : "inline-block",
                !isSpace && charGradientClass,
              )}
            >
              {chars.map(({ ch, gid }) => (
                <CharSpan
                  key={gid}
                  index={gid}
                  className={cn(charClassName, charGradientClass)}
                  timing={timing}
                  reveal={reveal}
                >
                  {ch}
                </CharSpan>
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
        className={cn("inline-block", gradient && "sbi-gradient")}
        style={
          gradient ? ({ "--sbi-gradient": gradient } as AnimStyle) : undefined
        }
      >
        {parts.map((part, i) => (
          <CharSpan
            key={baseId ? `${baseId}-${i}` : i}
            index={i}
            className={cn(charClassName, charGradientClass)}
            timing={timing}
            reveal={reveal}
          >
            {part}
          </CharSpan>
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

  const timing: CharTiming = {
    startDelay,
    charStagger,
    duration,
    blur,
    yOffset,
  };

  return createElement(
    as,
    { className: cn(className) },
    <TextInner
      text={text}
      parts={parts}
      splitBy={splitBy}
      gradient={gradient}
      charClassName="sbi-char sbi-anim sbi-immediate"
      timing={timing}
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

  const timing: CharTiming = {
    startDelay,
    charStagger,
    duration,
    blur,
    yOffset,
  };
  const reveal: CharReveal = { isVisible, animDone };

  return createElement(
    as,
    { className: cn(className) },
    <TextInner
      text={text}
      parts={parts}
      splitBy={splitBy}
      gradient={gradient}
      charClassName="sbi-char sbi-anim sbi-on-scroll"
      timing={timing}
      reveal={reveal}
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
    "--sbi-delay": `${delay}s`,
    "--sbi-duration": `${duration}s`,
    "--sbi-blur": `${blur}px`,
    "--sbi-y": `${yOffset}px`,
  };
  return createElement(
    as,
    { className: cn(className, "sbi-anim", "sbi-immediate"), style },
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

  const style: AnimStyle = {
    "--sbi-delay": `${delay}s`,
    "--sbi-duration": `${duration}s`,
    "--sbi-opacity": isVisible ? "1" : "0",
    "--sbi-filter": isVisible ? "blur(0px)" : `blur(${blur}px)`,
    "--sbi-transform": isVisible ? "none" : `translateY(${yOffset}px)`,
    "--sbi-will-change": animDone ? "auto" : "opacity, filter, transform",
  };

  return createElement(
    as,
    { ref, className: cn(className, "sbi-anim", "sbi-on-scroll"), style },
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
