"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

interface TypingAnimationProps {
  text: string;
  duration?: number;
  className?: string;
}

export default function TypingAnimation({
  text,
  duration = 200,
  className,
}: TypingAnimationProps) {
  const [displayedText, setDisplayedText] = useState<string>("");
  const [i, setI] = useState<number>(0);

  useEffect(() => {
    // Reset animation when text changes
    setDisplayedText("");
    setI(0);

    const typingEffect = setInterval(() => {
      if (i < text.length) {
        setDisplayedText(text.substring(0, i + 1));
        setI(i + 1);
      } else {
        clearInterval(typingEffect);
      }
    }, duration);

    return () => {
      clearInterval(typingEffect);
    };
  }, [text, duration, i]);

  return (
    <h1
      className={cn(
        "font-display text-center text-4xl leading-[5rem] font-bold tracking-[-0.02em] drop-shadow-xs",
        className,
      )}
    >
      {displayedText ? displayedText : text}
    </h1>
  );
}
