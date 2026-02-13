"use client";

import { m } from "motion/react";
import { type ComponentType, type ReactNode, Suspense } from "react";

import SuspenseLoader from "@/components/shared/SuspenseLoader";

interface AnimatedSectionProps {
  children?: ReactNode;
  fallback?: ReactNode;
  delay?: number;
  duration?: number;
  className?: string;
}

/**
 * AnimatedSection - A wrapper component that combines Suspense with Framer Motion animations
 *
 * Features:
 * - Lazy loading with Suspense
 * - Fade-in animation on scroll
 * - Customizable animation timing
 * - Optional custom fallback
 */
export function AnimatedSection({
  children,
  fallback = <SuspenseLoader />,
  delay = 0,
  duration = 0.6,
  className,
}: AnimatedSectionProps) {
  return (
    <Suspense fallback={fallback}>
      <m.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-100px" }}
        transition={{
          duration,
          delay,
          ease: [0.25, 0.4, 0.25, 1],
        }}
        className={className}
      >
        {children}
      </m.div>
    </Suspense>
  );
}

/**
 * AnimatedLazySection - A wrapper for lazy-loaded components with animation
 *
 * Usage:
 * const MyComponent = lazy(() => import('./MyComponent'));
 * <AnimatedLazySection component={MyComponent} delay={0.2} />
 */
interface AnimatedLazySectionProps {
  component: ComponentType;
  fallback?: ReactNode;
  delay?: number;
  duration?: number;
  className?: string;
  componentProps?: Record<string, unknown>;
}

export function AnimatedLazySection({
  component: Component,
  fallback = <SuspenseLoader />,
  delay = 0,
  duration = 0.6,
  className,
  componentProps = {},
}: AnimatedLazySectionProps) {
  return (
    <Suspense fallback={fallback}>
      <m.div
        initial={{ opacity: 0, y: 20 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-100px" }}
        transition={{
          duration,
          delay,
          ease: [0.25, 0.4, 0.25, 1],
        }}
        className={className}
      >
        <Component {...componentProps} />
      </m.div>
    </Suspense>
  );
}
