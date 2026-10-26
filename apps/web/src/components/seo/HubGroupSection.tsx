import type { ReactNode } from "react";
import { SiteLink } from "@/components/seo/SiteLink";

interface HubGroupSectionProps {
  readonly heading: ReactNode;
  readonly children: ReactNode;
  readonly headingClassName?: string;
  /** Fragment id, for a hub's index to jump to. */
  readonly id?: string;
  /** The page listing everything this section previews. */
  readonly allLink?: { readonly href: string; readonly label: string };
}

/** A titled group of cards, with a link to the page holding the whole group when the section only previews it. */
export function HubGroupSection({
  heading,
  children,
  headingClassName = "text-3xl font-semibold text-white",
  id,
  allLink,
}: HubGroupSectionProps) {
  return (
    <section id={id} className="mb-16">
      <div className="mb-6 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-2">
        <h2 className={headingClassName}>{heading}</h2>
        {allLink && (
          <SiteLink
            href={allLink.href}
            className="text-sm text-zinc-400 hover:text-white"
          >
            {allLink.label}
          </SiteLink>
        )}
      </div>
      {children}
    </section>
  );
}
