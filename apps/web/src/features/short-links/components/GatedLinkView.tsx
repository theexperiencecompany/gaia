"use client";

import { Spinner } from "@heroui/spinner";
import { ApiError } from "@shared/api";
import { useEffect, useState } from "react";

import { resolveLinkInBrowser } from "../api/linkViewerApi";
import type { LinkResolution } from "../types";
import { linkUnavailableState } from "../utils/linkDenial";
import { LinkOpenBeacon } from "./LinkOpenBeacon";
import { LinkUnavailable } from "./LinkUnavailable";
import { PublicLinkView } from "./PublicLinkView";

async function resolveGated(slug: string): Promise<LinkResolution> {
  try {
    return { kind: "open", envelope: await resolveLinkInBrowser(slug) };
  } catch (error) {
    const state =
      error instanceof ApiError
        ? linkUnavailableState(slug, error.envelope)
        : null;
    if (!state) throw error;
    return { kind: "unavailable", state };
  }
}

/**
 * A people- or owner-only link, opened in the browser: only the browser holds
 * the viewer's session (the cookie is host-only on the API host), so server
 * rendering got a sign-in denial whoever is reading.
 */
export function GatedLinkView({ slug }: { slug: string }) {
  const [resolution, setResolution] = useState<LinkResolution | null>(null);
  const [failure, setFailure] = useState<unknown>(null);

  useEffect(() => {
    let current = true;
    resolveGated(slug).then(
      (result) => {
        if (current) setResolution(result);
      },
      (error: unknown) => {
        if (current) setFailure(error);
      },
    );
    return () => {
      current = false;
    };
  }, [slug]);

  // Rethrown during render so the route's error boundary shows it.
  if (failure) throw failure;
  if (!resolution) {
    return (
      <main className="flex min-h-dvh items-center justify-center bg-primary-bg">
        <Spinner size="lg" />
      </main>
    );
  }
  if (resolution.kind === "unavailable") {
    return <LinkUnavailable state={resolution.state} />;
  }
  return (
    <>
      <LinkOpenBeacon slug={slug} />
      <PublicLinkView slug={slug} envelope={resolution.envelope} />
    </>
  );
}
