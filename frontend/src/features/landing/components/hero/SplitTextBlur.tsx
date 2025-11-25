import { motion } from "framer-motion";
import React, { useId, useRef } from "react";

import { useIntersectionObserver } from "@/hooks/ui/useIntersectionObserver";
import { cn } from "@/lib/utils";

interface SplitTextBlurProps {
  text: string;
  className?: string;
  delay?: number;
  staggerDelay?: number;
  springConfig?: {
    stiffness: number;
    damping: number;
    mass: number;
  };
  yOffset?: number;
  disableIntersectionObserver?: boolean;
}

const SplitTextBlur = ({
  text,
  className = "",
  delay = 1,
  staggerDelay = 0.1,
  springConfig = {
    stiffness: 400,
    damping: 70,
    mass: 1,
  },
  yOffset = 2,
  disableIntersectionObserver = false,
}: SplitTextBlurProps) => {
  const ref = useRef<HTMLDivElement>(null);
  const isVisible = useIntersectionObserver(ref, { threshold: 0.1 });

  const words = text.split(" ");

  const containerVariants = {
    hidden: { opacity: 0 },
    visible: {
      opacity: 1,
      transition: {
        delay,
        when: "beforeChildren",
        staggerChildren: staggerDelay,
      },
    },
  };

  const wordVariants = {
    hidden: {
      opacity: 0,
      filter: "blur(10px)",
      y: yOffset,
    },
    visible: {
      opacity: 1,
      filter: "blur(0px)",
      y: 0,
      transition: {
        type: "spring" as const,
        stiffness: springConfig.stiffness,
        damping: springConfig.damping,
        mass: springConfig.mass,
      },
    },
  };

  const shouldAnimate = disableIntersectionObserver || isVisible;
  const baseId = useId();

  return (
    <motion.div
      ref={ref}
      initial="hidden"
      animate={shouldAnimate ? "visible" : "hidden"}
      variants={containerVariants}
      className={cn(className)}
      style={{
        willChange: "transform, opacity, filter",
        background: "linear-gradient(to bottom, #a3a3a3, #ffffff)",
        WebkitBackgroundClip: "text",
        WebkitTextFillColor: "transparent",
        backgroundClip: "text",
      }}
    >
      {words.map((word, index) => (
        <motion.span
          // biome-ignore lint/suspicious/noArrayIndexKey: mapping with word and base id and index
          key={baseId + word + index}
          variants={wordVariants}
          style={{
            willChange: "transform, opacity, filter",
            display: "inline-block",
            marginRight: index < words.length - 1 ? "0.25em" : "0",
            background: "inherit",
            WebkitBackgroundClip: "inherit",
            WebkitTextFillColor: "inherit",
            backgroundClip: "inherit",
            paddingBottom: "7px",
          }}
          className="font-serif"
        >
          {word}
        </motion.span>
      ))}
    </motion.div>
  );
};

export { SplitTextBlur };
