"use client";

import { useEffect, useState } from "react";

import type { LinkEnvelope } from "@/types/features/shortLinkTypes";

import { resolveLinkInBrowser } from "../api/linkViewerApi";
import { LinkOpenBeacon } from "./LinkOpenBeacon";
import { PublicLinkView } from "./PublicLinkView";

/**
 * A link the server opened, re-read in the browser: the server renders without
 * the viewer's session (the cookie is host-only on the API host), so only the
 * browser's read can tell the owner apart and give them the share controls.
 */
export function OpenLinkView({
  slug,
  envelope,
}: {
  slug: string;
  envelope: LinkEnvelope;
}) {
  const [ownerEnvelope, setOwnerEnvelope] = useState<LinkEnvelope | null>(null);

  useEffect(() => {
    let current = true;
    resolveLinkInBrowser(slug).then(
      (fresh) => {
        if (current && fresh.is_owner) setOwnerEnvelope(fresh);
      },
      (error: unknown) => {
        // The server's view already rendered; only the owner's controls are lost.
        console.error("Re-reading the link in the browser failed:", error);
      },
    );
    return () => {
      current = false;
    };
  }, [slug]);

  return (
    <>
      <LinkOpenBeacon slug={slug} />
      <PublicLinkView slug={slug} envelope={ownerEnvelope ?? envelope} />
    </>
  );
}
