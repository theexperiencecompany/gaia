"use client";

import { CircleArrowLeft02Icon } from "@icons";
import { m } from "motion/react";
import Image from "next/image";
import Link from "next/link";
import FAQAccordion from "@/components/seo/FAQAccordion";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import {
  CATEGORY_COLORS,
  type FeatureData,
  getFeatureBySlug,
} from "@/features/landing/data/featuresData";
import { FeatureDemoWrapper } from "./FeatureDemoWrapper";
import { FeatureIcon } from "./FeatureIcon";

interface Props {
  feature: FeatureData;
}

const ease = [0.22, 1, 0.36, 1] as const;

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-4 text-xs font-medium uppercase tracking-widest text-primary">
      {children}
    </p>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="font-serif mb-4 text-4xl font-normal text-white md:text-5xl">
      {children}
    </h2>
  );
}

function SectionSubtitle({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-12 text-base font-light leading-relaxed text-zinc-400">
      {children}
    </p>
  );
}

export function FeatureDetailClient({ feature }: Props) {
  const categoryColor = CATEGORY_COLORS[feature.category];

  return (
    <div className="w-full min-h-screen">
      {/* Hero — full-width gradient band */}
      <div className="relative overflow-hidden pt-24">
        <Image
          src="/images/wallpapers/bands_gradient_1.webp"
          alt=""
          fill
          className="object-cover pointer-events-none select-none"
          priority
        />
        {/* Fade into page bg at the bottom */}
        <div className="pointer-events-none absolute bottom-0 inset-x-0 h-40 bg-gradient-to-b from-transparent to-background" />

        {/* Back link */}
        <div className="relative z-10 px-6">
          <Link
            href="/features"
            className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1 transition-colors"
          >
            <CircleArrowLeft02Icon width={16} height={16} /> All features
          </Link>
        </div>

        {/* Hero text */}
        <section className="relative z-10 py-12 max-w-3xl mx-auto px-6 text-center">
          <m.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5, ease }}
            className="text-xs uppercase tracking-widest mb-4 font-medium"
            style={{ color: categoryColor.icon }}
          >
            {feature.category}
          </m.div>
          <m.h1
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease, delay: 0.1 }}
            className="font-serif text-5xl md:text-6xl lg:text-7xl font-normal text-white mb-6 leading-[1.1]"
          >
            {feature.headline}
          </m.h1>
          <m.p
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease, delay: 0.2 }}
            className="text-lg md:text-xl font-light leading-relaxed text-white/80 max-w-2xl mx-auto mb-10"
          >
            {feature.subheadline}
          </m.p>
          <m.div
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.7, ease, delay: 0.3 }}
          >
            <GetStartedButton
              text="Get started free"
              btnColor="#000000"
              classname="text-white! text-base h-12 rounded-2xl"
            />
          </m.div>
        </section>

        {/* Demo — inside the hero gradient */}
        <m.div
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease, delay: 0.4 }}
          className="relative z-10 max-w-4xl mx-auto px-6 pb-20"
        >
          <div className="rounded-3xl bg-zinc-800 p-4">
            <div className="rounded-3xl bg-zinc-900 p-4 md:p-6">
              <FeatureDemoWrapper demoComponent={feature.demoComponent} />
            </div>
          </div>
        </m.div>
      </div>

      {/* Benefits */}
      <m.section
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        viewport={{ once: true }}
        className="max-w-6xl mx-auto px-6 py-20 text-center"
      >
        <SectionLabel>{feature.category}</SectionLabel>
        <SectionHeading>Key capabilities</SectionHeading>
        <SectionSubtitle>What makes {feature.title} powerful.</SectionSubtitle>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-left">
          {feature.benefits.map((benefit) => (
            <div key={benefit.title} className="rounded-2xl bg-zinc-800 p-6">
              <div
                className="rounded-xl p-2 w-9 h-9 mb-4 flex items-center justify-center"
                style={{ background: categoryColor.bg }}
              >
                <FeatureIcon name={benefit.icon} color={categoryColor.icon} />
              </div>
              <h3 className="text-sm font-medium text-zinc-100 mb-2">
                {benefit.title}
              </h3>
              <p className="text-sm font-light text-zinc-400 leading-relaxed">
                {benefit.description}
              </p>
            </div>
          ))}
        </div>
      </m.section>

      {/* How it works */}
      {feature.howItWorks && (
        <m.section
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          viewport={{ once: true }}
          className="max-w-4xl mx-auto px-6 py-20 text-center"
        >
          <SectionLabel>How it works</SectionLabel>
          <SectionHeading>Three steps to get started.</SectionHeading>
          <SectionSubtitle>
            Set up in minutes. Works automatically from there.
          </SectionSubtitle>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 text-left">
            {feature.howItWorks.map((step) => (
              <div key={step.number} className="flex flex-col gap-2">
                <span className="text-4xl font-mono text-zinc-700">
                  {step.number}
                </span>
                <h3 className="text-sm font-medium text-zinc-100">
                  {step.title}
                </h3>
                <p className="text-sm font-light text-zinc-400">
                  {step.description}
                </p>
              </div>
            ))}
          </div>
        </m.section>
      )}

      {/* Use Cases */}
      {feature.useCases && (
        <m.section
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          viewport={{ once: true }}
          className="max-w-6xl mx-auto px-6 py-20 text-center"
        >
          <SectionLabel>Use cases</SectionLabel>
          <SectionHeading>How teams use this.</SectionHeading>
          <SectionSubtitle>Real workflows, real outcomes.</SectionSubtitle>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-left">
            {feature.useCases.map((uc) => (
              <div key={uc.title} className="rounded-2xl bg-zinc-800 p-6">
                <h3 className="text-sm font-medium text-zinc-100 mb-2">
                  {uc.title}
                </h3>
                <p className="text-sm font-light text-zinc-400 leading-relaxed">
                  {uc.description}
                </p>
              </div>
            ))}
          </div>
        </m.section>
      )}

      {/* FAQ */}
      {feature.faqs && (
        <m.section
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          viewport={{ once: true }}
          className="max-w-3xl mx-auto px-6 py-20 text-center"
        >
          <SectionLabel>FAQ</SectionLabel>
          <SectionHeading>Frequently asked questions.</SectionHeading>
          <SectionSubtitle>Everything you need to know.</SectionSubtitle>
          <div className="text-left">
            <FAQAccordion faqs={[...feature.faqs]} />
          </div>
        </m.section>
      )}

      {/* Related Features */}
      {feature.relatedSlugs && (
        <m.section
          initial={{ opacity: 0, y: 24 }}
          whileInView={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5 }}
          viewport={{ once: true }}
          className="max-w-6xl mx-auto px-6 py-20 text-center"
        >
          <SectionLabel>Related</SectionLabel>
          <SectionHeading>Features that work well together.</SectionHeading>
          <SectionSubtitle>
            Combine these with {feature.title} for more power.
          </SectionSubtitle>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-left">
            {feature.relatedSlugs.map((slug) => {
              const related = getFeatureBySlug(slug);
              if (!related) return null;
              const relatedColor = CATEGORY_COLORS[related.category];
              return (
                <Link
                  key={slug}
                  href={`/features/${slug}`}
                  className="rounded-2xl bg-zinc-800 p-6 hover:bg-zinc-700 transition-colors"
                >
                  <div
                    className="rounded-xl p-2 w-9 h-9 mb-4 flex items-center justify-center"
                    style={{ background: relatedColor.bg }}
                  >
                    <FeatureIcon
                      name={related.icon}
                      color={relatedColor.icon}
                    />
                  </div>
                  <h3 className="text-sm font-medium text-zinc-100 mb-1">
                    {related.title}
                  </h3>
                  <p className="text-xs font-light text-zinc-500 leading-relaxed">
                    {related.tagline}
                  </p>
                </Link>
              );
            })}
          </div>
        </m.section>
      )}

      <FinalSection />
    </div>
  );
}
