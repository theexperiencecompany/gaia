import NextLink from "next/link";
import type { ComponentProps } from "react";

import { Link as LocaleLink } from "@/i18n/navigation";
import { isTranslatedPath } from "@/i18n/translatedRoutes";

interface SiteLinkProps
  extends Omit<ComponentProps<typeof NextLink>, "href" | "locale"> {
  readonly href: string;
}

/** Marketing-page link: stays in the visitor's locale inside translated families, English everywhere else. */
export function SiteLink({ href, ...props }: SiteLinkProps) {
  if (isTranslatedPath(href)) return <LocaleLink href={href} {...props} />;
  return <NextLink href={href} {...props} />;
}
