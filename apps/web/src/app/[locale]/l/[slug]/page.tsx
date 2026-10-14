import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { cache } from "react";

import { PublicLinkView } from "@/features/short-links/components/PublicLinkView";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";
import type {
  PublicShortLinkView,
  ShortLinkTargetType,
} from "@/types/features/shortLinkTypes";

interface PageProps {
  params: Promise<{ slug: string }>;
}

// Link previews (Telegram, iMessage, Slack unfurls) are cached by third parties
// and shown to whoever sees the message, so they carry only the artifact's
// kind — never its title, contents or owner.
const PREVIEW_COPY: Record<
  ShortLinkTargetType,
  { title: string; description: string }
> = {
  todo_deliverable: {
    title: "Shared from GAIA",
    description: "Something GAIA worked on, shared with you.",
  },
  briefing: {
    title: "A GAIA brief",
    description: "A daily brief from GAIA, the proactive personal assistant.",
  },
  session_artifact: {
    title: "A file from GAIA",
    description: "A file GAIA made, shared with you.",
  },
  workflow_run: {
    title: "A GAIA workflow run",
    description: "What a GAIA workflow did, shared with you.",
  },
};

/**
 * Names the viewer to the API, whose resolver limit is per client IP. Without
 * it every server render arrives from this server's own address, so all
 * viewers share one budget and a burst of opens turns into 429 errors.
 * `cf-connecting-ip` is set by Cloudflare; self-hosted proxies set the first
 * `x-forwarded-for` hop.
 */
async function viewerForwardingHeaders(): Promise<Record<string, string>> {
  const incoming = await headers();
  const viewerIp =
    incoming.get("cf-connecting-ip") ??
    incoming.get("x-forwarded-for")?.split(",")[0]?.trim();
  return viewerIp ? { "X-Forwarded-For": viewerIp } : {};
}

/**
 * The public view behind a slug, fetched on the server with no caching —
 * the owner can revoke a link at any moment. `null` means unknown, revoked or
 * deleted (the API answers 404 for all three); any other failure throws.
 * `cache` dedupes the call between `generateMetadata` and the page.
 */
const fetchPublicView = cache(
  async (slug: string): Promise<PublicShortLinkView | null> => {
    const apiBaseUrl = getServerApiBaseUrl();
    if (!apiBaseUrl) {
      throw new Error("API base URL is not configured for server rendering");
    }
    const response = await fetch(
      `${apiBaseUrl}/l/${encodeURIComponent(slug)}`,
      { cache: "no-store", headers: await viewerForwardingHeaders() },
    );
    if (response.status === 404) return null;
    if (!response.ok) {
      throw new Error(`Short link ${slug} failed with ${response.status}`);
    }
    return (await response.json()) as PublicShortLinkView;
  },
);

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const view = await fetchPublicView(slug);
  if (!view) notFound();
  const copy = PREVIEW_COPY[view.target_type];
  return {
    title: copy.title,
    description: copy.description,
    robots: { index: false, follow: false },
    openGraph: { title: copy.title, description: copy.description },
    twitter: { title: copy.title, description: copy.description },
  };
}

// Public capability-link page: lives OUTSIDE the (main) route group on purpose,
// so a signed-out viewer (tapping a link inside Telegram or an email) never
// mounts the authed app shell or its onboarding/auth guards.
export default async function ShortLinkPage({ params }: PageProps) {
  const { slug } = await params;
  const view = await fetchPublicView(slug);
  if (!view) notFound();
  return <PublicLinkView slug={slug} view={view} />;
}
