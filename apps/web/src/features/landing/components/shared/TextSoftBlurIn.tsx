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

function useFreezeOnIntersect(
  ref: React.RefObject<HTMLElement | null>,
  threshold: number,
  skip: boolean,
): boolean {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (skip) {
      const id = requestAnimationFrame(() => setVisible(true));
      return () => cancelAnimationFrame(id);
    }

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
  }, [ref, threshold, skip]);

  return visible;
}

export function TextSoftBlurIn({
  text,
  as = "div",
  className,
  startDelay = 0.03,
  charStagger = 0.015,
  duration = 0.5,
  blur = 12,
  yOffset = 16,
  splitBy = "char",
  immediate = false,
  gradient,
  threshold = 0.15,
}: TextSoftBlurInProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const isVisible = useFreezeOnIntersect(ref, threshold, immediate);
  const baseId = useId();

  const parts = useMemo(() => {
    if (splitBy === "word") {
      const words = text.split(" ");
      return words.map((w, i) => (i < words.length - 1 ? `${w} ` : w));
    }
    return Array.from(text);
  }, [text, splitBy]);

  const totalAnimMs = useMemo(
    () => (startDelay + parts.length * charStagger + duration) * 1000,
    [startDelay, charStagger, duration, parts.length],
  );

  const [animDone, setAnimDone] = useState(false);
  useEffect(() => {
    if (!isVisible) return;
    const id = window.setTimeout(() => setAnimDone(true), totalAnimMs + 50);
    return () => window.clearTimeout(id);
  }, [isVisible, totalAnimMs]);

  const gradientStyle: CSSProperties | undefined = gradient
    ? {
        backgroundImage: gradient,
        WebkitBackgroundClip: "text",
        WebkitTextFillColor: "transparent",
        backgroundClip: "text",
        color: "transparent",
      }
    : undefined;

  const inner: ReactNode = (
    <span
      ref={ref}
      aria-hidden="true"
      className="inline-block"
      style={gradientStyle}
    >
      {parts.map((part, i) => {
        const delay = startDelay + i * charStagger;
        const charStyle: CSSProperties = {
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
          ...(gradient
            ? {
                backgroundImage: "inherit",
                WebkitBackgroundClip: "inherit",
                WebkitTextFillColor: "inherit",
                backgroundClip: "inherit",
              }
            : null),
        };
        return (
          <span
            // biome-ignore lint/suspicious/noArrayIndexKey: stable id + index
            key={`${baseId}-${i}`}
            style={charStyle}
          >
            {part}
          </span>
        );
      })}
    </span>
  );

  return createElement(
    as,
    { className: cn(className), "aria-label": text },
    inner,
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

export function SoftBlurInBlock({
  children,
  as = "div",
  className,
  delay = 0.03,
  duration = 0.55,
  blur = 12,
  yOffset = 16,
  immediate = false,
  threshold = 0.15,
}: SoftBlurInBlockProps) {
  const ref = useRef<HTMLElement>(null);
  const isVisible = useFreezeOnIntersect(ref, threshold, immediate);

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

  return createElement(as, { ref, className: cn(className), style }, children);
}
