import type { ReactNode } from "react";
import { SiteLink } from "@/components/seo/SiteLink";
import { cn } from "@/lib/utils";

interface LinkCardProps {
  readonly href: string;
  readonly title: ReactNode;
  readonly description: ReactNode;
  /** Cap the description at two lines, for text that varies in length. */
  readonly clamp?: boolean;
}

/** A marketing page's link to a related page: a titled card with one short description. */
export function LinkCard({ href, title, description, clamp }: LinkCardProps) {
  return (
    <SiteLink
      href={href}
      className="group rounded-2xl bg-zinc-800 p-5 transition-colors hover:bg-zinc-700/50"
    >
      <h3 className="mb-2 text-lg font-medium text-white transition-colors group-hover:text-primary">
        {title}
      </h3>
      <p
        className={cn(
          "text-sm leading-relaxed text-zinc-400",
          clamp && "line-clamp-2",
        )}
      >
        {description}
      </p>
    </SiteLink>
  );
}
