"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon } from "@icons";
import Link from "next/link";
import FAQAccordion from "@/components/seo/FAQAccordion";
import type { PublicIntegrationResponse } from "@/features/integrations/types";

import { getIntegrationFAQs } from "./faqs";

interface IntegrationRichContentProps {
  readonly integration: PublicIntegrationResponse;
  readonly comparisonSlug?: string;
}

export function IntegrationRichContent({
  integration,
  comparisonSlug,
}: IntegrationRichContentProps) {
  const howItWorksSteps =
    integration.content?.howItWorks && integration.content.howItWorks.length > 0
      ? integration.content.howItWorks.map((s, i) => ({
          step: String(i + 1),
          title: s.title,
          body: s.body,
        }))
      : null;
  const faqs = getIntegrationFAQs(integration);
  const { name, category } = integration;
  const categoryLabel = category.charAt(0).toUpperCase() + category.slice(1);

  return (
    <div className="space-y-12 mt-4">
      {/* Section 2: How it works */}
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
          {(
            howItWorksSteps ?? [
              {
                step: "1",
                title: `Connect ${name} to GAIA`,
                body: `Open the GAIA Marketplace, find the ${name} integration, and click "Add to your GAIA". Authorise access in under two minutes, no code, no configuration files.`,
              },
              {
                step: "2",
                title: "Tell GAIA what to automate in plain English",
                body: `Describe the task in your own words: "summarise my ${name} activity every morning" or "notify me on Slack when a new ${categoryLabel.toLowerCase()} event happens". GAIA understands context and intent.`,
              },
              {
                step: "3",
                title: "GAIA handles it automatically, 24/7",
                body: `GAIA runs your ${name} automations in the background around the clock. No manual triggers, no scripts to maintain, just results delivered to you.`,
              },
            ]
          ).map(({ step, title, body }) => (
            <li key={step} className="flex gap-5">
              <div className="flex-shrink-0 flex items-start pt-0.5">
                <span className="h-8 w-8 rounded-full bg-[#00bbff]/10 flex items-center justify-center text-[#00bbff] text-sm font-semibold">
                  {step}
                </span>
              </div>
              <div>
                <p className="text-zinc-200 font-medium text-sm mb-1">
                  {title}
                </p>
                <p className="text-zinc-400 text-sm leading-relaxed">{body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      {/* Section 3: FAQ */}
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

      {/* Section 4: Related integrations CTA */}
      <section className="rounded-3xl bg-gradient-to-br from-zinc-900/70 to-zinc-900/40 backdrop-blur-md p-8 space-y-4">
        <h2 className="text-2xl font-medium text-foreground">
          GAIA connects {name} with your entire stack
        </h2>
        <p className="text-zinc-400 text-sm leading-relaxed max-w-2xl">
          {name} is just one piece of the puzzle. GAIA integrates with 50+ tools
          across {categoryLabel.toLowerCase()}, communication, productivity, and
          more, letting you build cross-tool automations in plain English
          without writing a single line of code.
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

      {/* Cross-link to comparison page when one exists */}
      {comparisonSlug && (
        <p className="text-sm text-zinc-500 border-t border-zinc-800/50 pt-4">
          Evaluating your options?{" "}
          <Link
            href={`/compare/${comparisonSlug}`}
            className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
          >
            Compare GAIA vs {name} &rarr;
          </Link>
        </p>
      )}
    </div>
  );
}
