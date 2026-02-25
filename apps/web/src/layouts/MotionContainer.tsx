import { type MotionProps, m } from "motion/react";
import React, { Children, useMemo, useRef } from "react";

import { useIntersectionObserver } from "@/hooks/ui/useIntersectionObserver";
import { cn } from "@/lib/utils";

interface AnimatedSectionProps
  extends MotionProps,
    Omit<React.HTMLAttributes<HTMLDivElement>, keyof MotionProps> {
  children: React.ReactNode;
  staggerDelay?: number;
  className?: string;
  childClassName?: string; // New prop for span classes
  disableAnimation?: boolean;
  disableIntersectionObserver?: boolean; // New prop to disable intersection observer
}

const STATIC_ITEM_VARIANTS = {
  hidden: { opacity: 0, filter: "blur(10px)" },
  visible: {
    opacity: 1,
    filter: "blur(0px)",
    transition: {
      duration: 0.8,
      ease: "easeOut",
    },
  },
};

const NO_ANIMATION_VARIANTS = {
  visible: { opacity: 1, filter: "blur(0px)" },
};

const AnimatedSectionComponent = ({
  children,
  staggerDelay = 0.4,
  className = "",
  childClassName = "",
  disableAnimation = false,
  disableIntersectionObserver = false,
  ...restProps
}: AnimatedSectionProps) => {
  const ref = useRef<HTMLDivElement>(null);
  const isVisible = useIntersectionObserver(ref, { threshold: 0.1 });

  const containerVariants = useMemo(
    () => ({
      hidden: { opacity: 0 },
      visible: {
        opacity: 1,
        transition: disableAnimation
          ? {}
          : {
              when: "beforeChildren",
              staggerChildren: staggerDelay,
            },
      },
    }),
    [staggerDelay, disableAnimation],
  );

  const shouldAnimate =
    disableAnimation || disableIntersectionObserver || isVisible;

  return (
    <m.div
      ref={ref}
      initial={disableAnimation ? "visible" : "hidden"}
      animate={shouldAnimate ? "visible" : "hidden"}
      variants={containerVariants}
      className={cn(className)}
      {...restProps}
    >
      {Children.map(children, (child, index) => {
        const key =
          React.isValidElement(child) && child.key != null ? child.key : index;
        return (
          <m.span
            key={key}
            variants={
              disableAnimation ? NO_ANIMATION_VARIANTS : STATIC_ITEM_VARIANTS
            }
            className={cn(childClassName)}
          >
            {child}
          </m.span>
        );
      })}
    </m.div>
  );
};

export const MotionContainer = React.memo(AnimatedSectionComponent);
