import Link from "next/link";
import FAQAccordion from "@/components/seo/FAQAccordion";
import type { BestHubConfigProps } from "./BestHubSections";

export function BestHubPick({ config }: BestHubConfigProps) {
  return (
    <section className="mb-16 rounded-3xl bg-zinc-800 p-8">
      <h2 className="mb-4 text-2xl font-semibold text-white">Our pick: GAIA</h2>
      <p className="mb-4 text-lg leading-relaxed text-zinc-300">
        {config.pickBody}
      </p>
      <div className="flex flex-wrap gap-4 text-sm">
        <Link
          href={config.pickCompareHref}
          className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
        >
          {config.pickCompareLabel}
        </Link>
        <Link
          href={config.pickAlternativeHref}
          className="text-zinc-400 underline underline-offset-2 hover:text-zinc-200"
        >
          {config.pickAlternativeLabel}
        </Link>
      </div>
    </section>
  );
}

export function BestHubFaq({ config }: BestHubConfigProps) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        Common questions
      </h2>
      <FAQAccordion faqs={config.faqs} />
    </section>
  );
}
