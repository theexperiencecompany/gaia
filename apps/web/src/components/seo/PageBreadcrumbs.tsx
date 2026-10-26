"use client";

import { BreadcrumbItem, Breadcrumbs } from "@heroui/react";
import { useLocale } from "next-intl";

import { getPathname } from "@/i18n/navigation";
import { isTranslatedPath } from "@/i18n/translatedRoutes";

export interface PageCrumb {
  readonly label: string;
  /** Omitted on the last crumb, which is the current page. */
  readonly href?: string;
}

const ITEM_CLASSES = {
  item: "text-sm text-zinc-400 decoration-zinc-600 hover:text-zinc-200 data-[current=true]:text-zinc-100 data-[current=true]:decoration-transparent",
  separator: "text-zinc-600",
};

/** The one breadcrumb trail for marketing pages; links keep the locale only inside translated families. */
export function PageBreadcrumbs({
  items,
  className,
}: {
  readonly items: readonly PageCrumb[];
  readonly className?: string;
}) {
  const locale = useLocale();
  const localize = (href: string) =>
    isTranslatedPath(href) ? getPathname({ href, locale }) : href;

  return (
    <Breadcrumbs
      className={className}
      itemClasses={ITEM_CLASSES}
      underline="always"
    >
      {items.map((crumb) => (
        <BreadcrumbItem
          key={crumb.label}
          href={crumb.href ? localize(crumb.href) : undefined}
        >
          {crumb.label}
        </BreadcrumbItem>
      ))}
    </Breadcrumbs>
  );
}
