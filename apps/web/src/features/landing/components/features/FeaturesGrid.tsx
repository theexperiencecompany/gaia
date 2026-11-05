"use client";

import { Chip, Description, InputGroup, Kbd, Label, TextField } from "@heroui/react";
import { ArrowRight02Icon, Search01Icon } from "@icons";
import type { Easing, Variants } from "motion/react";
import * as m from "motion/react-m";
import Link from "next/link";
import { type ReactNode, useEffect, useRef, useState } from "react";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import LazyMotionProvider from "@/features/landing/components/LazyMotionProvider";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import {
  CATEGORY_COLORS,
  FEATURE_CATEGORIES,
  getFeaturesByCategory,
} from "@/features/landing/data/featuresData";
import { FeatureIcon } from "./FeatureIcon";

const ease = [0.22, 1, 0.36, 1] as const;
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

/** The searchable feature catalogue; children render after it, above the closing CTA. */
export function FeaturesGrid({ children }: { children?: ReactNode }) {
  const [search, setSearch] = useState("");
  const query = search.toLowerCase().trim();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key === "f") {
        e.preventDefault();
        inputRef.current?.focus();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, []);

  return (
    <LazyMotionProvider>
      {/* Hero */}
      <section className="relative flex flex-col items-center justify-center overflow-hidden px-6 pb-20 pt-32 text-center">
        <div className="absolute inset-0 -z-10">
          <ProgressiveImage
            webpSrc="/images/wallpapers/bands_gradient_1.webp"
            pngSrc="/images/wallpapers/bands_gradient_1.webp"
            alt="Gradient background"
            className="object-cover"
            shouldHaveInitialFade
            priority
          />
        </div>

        <m.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="relative z-10 mb-6"
        >
          <Chip
            variant="tertiary"
            color="accent"
            size="md"
            className="text-primary"
          >
            Features
          </Chip>
        </m.div>

        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
        >
          Everything GAIA can do.
        </m.h1>

        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-white"
        >
          Everything GAIA can do across AI intelligence, productivity,
          automation, integrations, and every platform you use.
        </m.p>

        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.3 }}
          className="relative z-10"
        >
          <GetStartedButton
            text="Get started"
            btnColor="#000000"
            classname="text-base h-12 rounded-2xl"
          />
        </m.div>
      </section>

      {/* Feature categories */}
      <div className="mx-auto max-w-6xl px-6 py-16">
        {/* Search */}
        <m.div
          initial={{ opacity: 0, y: 12 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4, ease }}
          viewport={{ once: true }}
          className="mb-10 flex justify-center"
        >
          <TextField value={search} onChange={setSearch} className="max-w-md">
            <Label className="sr-only">Search features</Label>
            <Description className="sr-only">Search features by name or category</Description>
            <InputGroup>
              <InputGroup.Prefix>
                <Search01Icon className="size-4 shrink-0" />
              </InputGroup.Prefix>
              <input
                ref={inputRef}
                type="text"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                aria-label="Search features"
                placeholder="Search features..."
                className="input-group__input"
              />
              {!search && (
                <InputGroup.Suffix>
                  <Kbd className="text-xs">
                    <Kbd.Abbr keyValue="ctrl" />F
                  </Kbd>
                </InputGroup.Suffix>
              )}
            </InputGroup>
          </TextField>
        </m.div>

        {FEATURE_CATEGORIES.map((category) => {
          const allFeatures = getFeaturesByCategory(category);
          const features = query
            ? allFeatures.filter(
                (f) =>
                  f.title.toLowerCase().includes(query) ||
                  f.tagline.toLowerCase().includes(query),
              )
            : allFeatures;
          if (features.length === 0) return null;
          return (
            <section key={category} className="mb-16">
              <p className="mb-4 mt-12 text-xs font-medium uppercase tracking-widest text-primary">
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
                            className="flex h-9 w-9 items-center justify-center rounded-xl"
                            style={{ background: color.bg }}
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
      </div>
      {children}
      <FinalSection />
    </LazyMotionProvider>
  );
}
