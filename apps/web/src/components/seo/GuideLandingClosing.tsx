import FAQAccordion from "@/components/seo/FAQAccordion";
import { SiteLink } from "@/components/seo/SiteLink";
import type {
  GuideFaq,
  GuideLink,
} from "@/features/guides/data/guidesData.types";

export function GuideFaqSection({ faqs }: { readonly faqs: GuideFaq[] }) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">
        Common questions
      </h2>
      <FAQAccordion faqs={faqs} />
    </section>
  );
}

export function GuideRelatedLinks({
  links,
}: {
  readonly links: readonly GuideLink[];
}) {
  return (
    <section className="mb-16">
      <h2 className="mb-6 text-3xl font-semibold text-white">Keep reading</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        {links.map((link) => (
          <SiteLink
            key={link.href}
            href={link.href}
            className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
          >
            <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
              {link.label}
            </h3>
            <p className="text-sm leading-relaxed text-zinc-400">
              {link.description}
            </p>
          </SiteLink>
        ))}
      </div>
    </section>
  );
}
