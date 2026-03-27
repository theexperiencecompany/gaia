"use client";

import { ArrowRight02Icon } from "@icons";
import type { Easing, Variants } from "motion/react";
import { m } from "motion/react";
import Link from "next/link";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import LargeHeader from "@/features/landing/components/shared/LargeHeader";
import {
  CATEGORY_COLORS,
  FEATURE_CATEGORIES,
  getFeaturesByCategory,
} from "@/features/landing/data/featuresData";
import { FeatureIcon } from "./FeatureIcon";

const EASE_OUT: Easing = "easeOut";

const containerVariants: Variants = {
  hidden: {},
  visible: { transition: { staggerChildren: 0.05 } },
};

const cardVariants: Variants = {
  hidden: { opacity: 0, y: 16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: 0.4, ease: EASE_OUT },
  },
};

export function FeaturesGrid() {
  return (
    <LazyMotionProvider>
      <div className="min-h-screen bg-[#111111]">
        <div className="mx-auto max-w-6xl px-6 py-16">
          <div className="flex justify-center mb-12">
            <LargeHeader
              chipText="Features"
              headingText="Everything GAIA can do"
              subHeadingText="30 capabilities across AI, productivity, automation, integrations, and every platform you use."
              centered
            />
          </div>

          {FEATURE_CATEGORIES.map((category) => {
            const features = getFeaturesByCategory(category);
            return (
              <section key={category} className="mb-16">
                <p className="mb-4 mt-12 text-xs font-medium uppercase tracking-widest text-[#00bbff]">
                  {category}
                </p>
                <m.div
                  className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3"
                  variants={containerVariants}
                  initial="hidden"
                  whileInView="visible"
                  viewport={{ once: true, margin: "-50px" }}
                >
                  {features.map((feature) => {
                    const color = CATEGORY_COLORS[category];
                    return (
                      <m.div
                        key={feature.slug}
                        variants={cardVariants}
                        className="h-full"
                      >
                        <Link
                          href={`/features/${feature.slug}`}
                          className="flex h-full flex-col rounded-2xl bg-zinc-800/50 p-5 transition-colors hover:bg-zinc-800"
                        >
                          <div className="flex items-center justify-between">
                            <div
                              className={`flex h-9 w-9 items-center justify-center rounded-xl ${color.bg}`}
                            >
                              <FeatureIcon
                                name={feature.icon}
                                color={color.icon}
                              />
                            </div>
                            <ArrowRight02Icon
                              size={16}
                              className="text-zinc-500"
                            />
                          </div>
                          <p className="mt-3 text-sm font-medium text-zinc-100">
                            {feature.title}
                          </p>
                          <p className="mt-1 text-xs font-light leading-relaxed text-zinc-400">
                            {feature.tagline}
                          </p>
                        </Link>
                      </m.div>
                    );
                  })}
                </m.div>
              </section>
            );
          })}

          <div className="mt-16 flex flex-col items-center gap-4 pb-16 text-center">
            <p className="text-lg font-light text-zinc-300">
              Start using GAIA free
            </p>
            <GetStartedButton />
          </div>
        </div>
      </div>
    </LazyMotionProvider>
  );
}
