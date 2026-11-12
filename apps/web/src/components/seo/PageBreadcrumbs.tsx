"use client";

import { useLocale } from "next-intl";

import { ChevronRight } from "@/components/shared/icons";

import { getPathname } from "@/i18n/navigation";
import { isTranslatedPath } from "@/i18n/translatedRoutes";

export interface PageCrumb {
  readonly label: string;
  /** Omitted on the last crumb, which is the current page. */
  readonly href?: string;
}

const LINK_CLASSES =
  "text-sm text-zinc-400 underline decoration-zinc-600 hover:text-zinc-200";

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
    <nav aria-label="Breadcrumb" className={className}>
      <ol className="flex items-center">
        {items.map((crumb, index) => {
          const isLast = index === items.length - 1;

          return (
            <li key={crumb.label} className="flex items-center">
              {crumb.href ? (
                <a href={localize(crumb.href)} className={LINK_CLASSES}>
                  {crumb.label}
                </a>
              ) : (
                <span
                  aria-current={isLast ? "page" : undefined}
                  className="text-sm text-zinc-100"
                >
                  {crumb.label}
                </span>
              )}
              {!isLast && (
                <ChevronRight
                  aria-hidden="true"
                  className="mx-1.5 size-3 text-zinc-600"
                />
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
