"use client";

import { Spinner } from "@heroui/spinner";
import { ApiError } from "@shared/api";
import { useEffect, useState } from "react";

import { openLinkInBrowser } from "../api/linkViewerApi";
import type { GatedOutcome, LinkResolution } from "../types";
import { linkUnavailableState } from "../utils/linkDenial";
import { LinkUnavailable } from "./LinkUnavailable";
import { PublicLinkView } from "./PublicLinkView";

async function resolveGated(slug: string): Promise<LinkResolution> {
  try {
    return { kind: "open", envelope: await openLinkInBrowser(slug) };
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
 * A link server rendering could not open, opened again in the browser: only the
 * browser holds the viewer's session (the cookie is host-only on the API host),
 * so a people- or owner-only link, or one its owner turned off, answered the
 * server as it answers a stranger.
 */
export function GatedLinkView({ slug }: { slug: string }) {
  const [outcome, setOutcome] = useState<GatedOutcome | null>(null);

  useEffect(() => {
    let current = true;
    resolveGated(slug).then(
      (resolution) => {
        if (current) setOutcome({ resolution });
      },
      (failure: unknown) => {
        if (current) setOutcome({ failure });
      },
    );
    return () => {
      current = false;
    };
  }, [slug]);

  // Rethrown during render so the route's error boundary shows it.
  if (outcome && "failure" in outcome) throw outcome.failure;
  const resolution = outcome?.resolution;
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
  return <PublicLinkView slug={slug} envelope={resolution.envelope} />;
}
