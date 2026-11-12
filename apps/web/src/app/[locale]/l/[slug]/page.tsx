import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { cache } from "react";

import { GatedLinkView } from "@/features/short-links/components/GatedLinkView";
import { LinkOpenBeacon } from "@/features/short-links/components/LinkOpenBeacon";
import { LinkUnavailable } from "@/features/short-links/components/LinkUnavailable";
import { PublicLinkView } from "@/features/short-links/components/PublicLinkView";
import type { LinkResolution } from "@/features/short-links/types";
import { isUnfurlBot } from "@/features/short-links/utils/isUnfurlBot";
import { linkUnavailableState } from "@/features/short-links/utils/linkDenial";
import { internalApiHeaders } from "@/lib/internalApiHeaders";
import { getServerApiBaseUrl } from "@/lib/serverApiBaseUrl";
import type {
  ErrorEnvelope,
  LinkEnvelope,
  LinkPreviewMeta,
} from "@/types/features/shortLinkTypes";

interface PageProps {
  params: Promise<{ slug: string }>;
}

const OG_SITE_NAME = "GAIA";
const OG_IMAGE_WIDTH = 1200;
const OG_IMAGE_HEIGHT = 630;

async function linkApiFetch(path: string): Promise<Response> {
  const apiBaseUrl = getServerApiBaseUrl();
  if (!apiBaseUrl) {
    throw new Error("API base URL is not configured for server rendering");
  }
  // No caching: the owner can revoke or narrow a link at any moment. The
  // headers name the viewer, so the API rate-limits each viewer, not this server.
  return fetch(`${apiBaseUrl}${path}`, {
    cache: "no-store",
    headers: internalApiHeaders(await headers()),
  });
}

/** What a preview may show for the link, by its access level and state; `cache` dedupes it per render. */
const fetchLinkMeta = cache(async (slug: string): Promise<LinkPreviewMeta> => {
  const response = await linkApiFetch(`/l/${encodeURIComponent(slug)}/meta`);
  if (!response.ok) {
    // Never the slug: it is a working link, and this message reaches Sentry.
    throw new Error(`Short link meta failed with ${response.status}`);
  }
  return (await response.json()) as LinkPreviewMeta;
});

/**
 * Open the link as an anonymous viewer: this server never sees the viewer's
 * session, so a people or owner link answers a sign-in denial here and is
 * opened again from the browser.
 */
async function resolveLinkOnServer(slug: string): Promise<LinkResolution> {
  const response = await linkApiFetch(`/l/${encodeURIComponent(slug)}`);
  if (response.ok) {
    return { kind: "open", envelope: (await response.json()) as LinkEnvelope };
  }
  const envelope = (await response.json().catch(() => undefined)) as
    | ErrorEnvelope
    | undefined;
  const state = linkUnavailableState(slug, envelope);
  if (!state) {
    throw new Error(`Short link resolve failed with ${response.status}`);
  }
  return { kind: "unavailable", state };
}

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const meta = await fetchLinkMeta(slug);
  // The generated card lives on whichever host served this page: the site-wide
  // metadataBase is GAIA Cloud's, which would point a self-host's previews there.
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host");
  const proto = requestHeaders.get("x-forwarded-proto") ?? "https";
  const card = `/api/og/link?slug=${encodeURIComponent(slug)}`;
  const image = {
    url: meta.image_url ?? (host ? `${proto}://${host}${card}` : card),
    width: OG_IMAGE_WIDTH,
    height: OG_IMAGE_HEIGHT,
  };
  return {
    title: meta.title,
    description: meta.description,
    robots: { index: meta.indexable, follow: meta.indexable },
    openGraph: {
      title: meta.title,
      description: meta.description,
      siteName: OG_SITE_NAME,
      images: [image],
    },
    twitter: {
      card: "summary_large_image",
      title: meta.title,
      description: meta.description,
      images: [image.url],
    },
  };
}

// Public capability-link page: lives OUTSIDE the (main) route group on purpose,
// so a signed-out viewer (tapping a link inside Telegram or an email) never
// mounts the authed app shell or its onboarding/auth guards.
export default async function ShortLinkPage({ params }: PageProps) {
  const { slug } = await params;
  // A chat-preview bot reads only the metadata; it never resolves the link.
  if (isUnfurlBot((await headers()).get("user-agent"))) return null;

  const resolution = await resolveLinkOnServer(slug);
  if (resolution.kind === "open") {
    return (
      <>
        <LinkOpenBeacon slug={slug} />
        <PublicLinkView slug={slug} envelope={resolution.envelope} />
      </>
    );
  }
  const { state } = resolution;
  if (state.denial === "link_not_found") notFound();
  if (
    state.denial === "link_sign_in_required" ||
    state.denial === "link_forbidden"
  ) {
    return <GatedLinkView slug={slug} />;
  }
  // The App Router answers 200 here; only notFound() can set a status.
  return <LinkUnavailable state={state} />;
}
