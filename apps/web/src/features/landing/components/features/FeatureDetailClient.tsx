"use client";

import { m } from "motion/react";
import Link from "next/link";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import type { FeatureData } from "@/features/landing/data/featuresData";
import { FeatureDemoWrapper } from "./FeatureDemoWrapper";

interface Props {
  feature: FeatureData;
}

const ease = [0.22, 1, 0.36, 1] as const;

export function FeatureDetailClient({ feature }: Props) {
  return (
    <div className="w-full bg-[#111111] min-h-screen">
      {/* Back link */}
      <div className="pt-6 px-6">
        <Link
          href="/features"
          className="text-xs text-zinc-500 hover:text-zinc-300 flex items-center gap-1 transition-colors"
        >
          ← All features
        </Link>
      </div>

      {/* Hero */}
      <section className="pt-16 pb-12 max-w-3xl mx-auto px-6 text-center">
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease }}
          className="text-xs uppercase tracking-widest text-[#00bbff] mb-4"
        >
          {feature.category}
        </m.div>
        <m.h1
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.1 }}
          className="font-serif text-4xl md:text-5xl lg:text-6xl font-normal text-zinc-50 mb-6 leading-[1.1]"
        >
          {feature.headline}
        </m.h1>
        <m.p
          initial={{ opacity: 0, y: 24 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.2 }}
          className="text-base md:text-lg font-light text-zinc-400 max-w-2xl mx-auto mb-8"
        >
          {feature.subheadline}
        </m.p>
        <m.div
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.7, ease, delay: 0.3 }}
        >
          <GetStartedButton />
        </m.div>
      </section>

      {/* Demo section */}
      <m.div
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        viewport={{ once: true }}
        className="max-w-4xl mx-auto px-6 py-8"
      >
        <div className="rounded-2xl bg-zinc-800 p-4">
          <div className="rounded-2xl bg-zinc-900 p-4 md:p-6">
            <FeatureDemoWrapper demoComponent={feature.demoComponent} />
          </div>
        </div>
      </m.div>

      {/* Benefits */}
      <m.section
        initial={{ opacity: 0, y: 24 }}
        whileInView={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        viewport={{ once: true }}
        className="max-w-6xl mx-auto px-6 py-16"
      >
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {feature.benefits.map((benefit) => (
            <div key={benefit.title} className="rounded-2xl bg-zinc-800 p-6">
              <div className="bg-[#00bbff]/10 rounded-xl p-2 w-9 h-9 mb-4 flex items-center justify-center">
                <span className="text-[#00bbff] text-sm">✦</span>
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
          className="max-w-4xl mx-auto px-6 py-12"
        >
          <h2 className="text-2xl font-serif font-normal text-zinc-50 text-center mb-10">
            How it works
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
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

      <FinalSection />
    </div>
  );
}
