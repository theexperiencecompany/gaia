import { Fragment } from "react";
import { SiteLink } from "@/components/seo/SiteLink";

interface Crumb {
  readonly label: string;
  /** Absent on the last crumb: the page itself. */
  readonly href?: string;
}

/** The visible breadcrumb trail of a hub's group page: Home / Hub / Group. */
export function HubBreadcrumb({
  crumbs,
}: {
  readonly crumbs: readonly Crumb[];
}) {
  return (
    <nav className="mb-8 text-sm text-zinc-500">
      {crumbs.map((crumb, index) => (
        <Fragment key={crumb.label}>
          {index > 0 && <span className="mx-2">/</span>}
          {crumb.href ? (
            <SiteLink href={crumb.href} className="hover:text-zinc-300">
              {crumb.label}
            </SiteLink>
          ) : (
            <span className="text-zinc-300">{crumb.label}</span>
          )}
        </Fragment>
      ))}
    </nav>
  );
}
