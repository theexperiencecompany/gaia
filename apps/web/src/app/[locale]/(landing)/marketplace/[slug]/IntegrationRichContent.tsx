"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon } from "@icons";
import Link from "next/link";
import FAQAccordion from "@/components/seo/FAQAccordion";
import type { PublicIntegrationResponse } from "@/features/integrations/types";

interface IntegrationRichContentProps {
  readonly integration: PublicIntegrationResponse;
  readonly comparisonSlug?: string;
  readonly alternativeSlug?: string;
}

export function IntegrationRichContent({
  integration,
  comparisonSlug,
  alternativeSlug,
}: IntegrationRichContentProps) {
  const howItWorks = integration.content?.howItWorks ?? [];
  const faqs = integration.content?.faqs ?? [];
  const { name, category } = integration;
  const categoryLabel = category.charAt(0).toUpperCase() + category.slice(1);

  return (
    <div className="space-y-12 mt-4">
      {howItWorks.length > 0 && (
        <section className="rounded-3xl bg-zinc-900/50 backdrop-blur-md p-8 space-y-6">
          <div>
            <h2 className="text-2xl font-medium text-foreground mb-2">
              How it works
            </h2>
            <p className="text-zinc-400 text-sm leading-relaxed">
              Set up your {name} automation in three simple steps, no code
              required.
            </p>
          </div>
          <ol className="space-y-4">
            {howItWorks.map(({ title, body }, index) => (
              <li key={title} className="flex gap-5">
                <div className="flex-shrink-0 flex items-start pt-0.5">
                  <span className="h-8 w-8 rounded-full bg-[#00bbff]/10 flex items-center justify-center text-[#00bbff] text-sm font-semibold">
                    {index + 1}
                  </span>
                </div>
                <div>
                  <p className="text-zinc-200 font-medium text-sm mb-1">
                    {title}
                  </p>
                  <p className="text-zinc-400 text-sm leading-relaxed">
                    {body}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}

      {faqs.length > 0 && (
        <section className="rounded-3xl bg-zinc-900/50 backdrop-blur-md p-8 space-y-4">
          <div>
            <h2 className="text-2xl font-medium text-foreground mb-2">
              Frequently asked questions
            </h2>
            <p className="text-zinc-400 text-sm leading-relaxed">
              Everything you need to know about the GAIA {name} integration.
            </p>
          </div>
          <FAQAccordion faqs={faqs} />
        </section>
      )}

      {/* Section 4: Related integrations CTA */}
      <section className="rounded-3xl bg-gradient-to-br from-zinc-900/70 to-zinc-900/40 backdrop-blur-md p-8 space-y-4">
        <h2 className="text-2xl font-medium text-foreground">
          GAIA connects {name} with your entire stack
        </h2>
        <p className="text-zinc-400 text-sm leading-relaxed max-w-2xl">
          {name} is just one piece of the puzzle. GAIA integrates with the rest
          of your tools across {categoryLabel.toLowerCase()}, communication,
          productivity, and more, letting you build cross-tool automations in
          plain English without writing a single line of code.
        </p>
        <Button
          as={Link}
          href="/marketplace"
          variant="flat"
          color="primary"
          endContent={
            <ArrowRight02Icon className="h-3.5 w-3.5" aria-hidden="true" />
          }
        >
          Browse all integrations
        </Button>
      </section>

      {/* Cross-links to comparison and alternative guides when they exist */}
      {(comparisonSlug || alternativeSlug) && (
        <div className="space-y-2 border-t border-zinc-800/50 pt-4 text-sm text-zinc-500">
          {comparisonSlug && (
            <p>
              Evaluating your options?{" "}
              <Link
                href={`/compare/${comparisonSlug}`}
                className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
              >
                Compare GAIA vs {name}
              </Link>
            </p>
          )}
          {alternativeSlug && (
            <p>
              Looking to switch?{" "}
              <Link
                href={`/alternative-to/${alternativeSlug}`}
                className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
              >
                Best {name} alternative guide
              </Link>
            </p>
          )}
        </div>
      )}
    </div>
  );
}
