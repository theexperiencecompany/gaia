import type { ReactNode } from "react";
import LandingLayoutShell from "@/components/layouts/LandingLayoutShell";
import JsonLd from "@/components/seo/JsonLd";
import { isSelfhostWeb } from "@/lib/selfhost";
import { generateOrganizationSchema, generateWebSiteSchema } from "@/lib/seo";

/** The public site: every page declares the GAIA Organization and WebSite its schemas refer to by @id. */
export default function LocaleLandingLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <>
      <LandingLayoutShell selfhost={isSelfhostWeb()}>
        {children}
      </LandingLayoutShell>
      <JsonLd data={[generateOrganizationSchema(), generateWebSiteSchema()]} />
    </>
  );
}
