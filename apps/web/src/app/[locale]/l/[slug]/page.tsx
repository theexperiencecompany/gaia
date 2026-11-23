import "../../../styles/app.css";
import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { cache } from "react";

import { GatedLinkView } from "@/features/short-links/components/GatedLinkView";
import { LinkUnavailable } from "@/features/short-links/components/LinkUnavailable";
import { OpenLinkView } from "@/features/short-links/components/OpenLinkView";
import { BROWSER_RESOLVED_DENIALS } from "@/features/short-links/constants";
import { isUnfurlBot } from "@/features/short-links/utils/isUnfurlBot";
import {
  fetchLinkMeta,
  resolveLinkOnServer,
} from "@/features/short-links/utils/linkServerApi";

interface PageProps {
  params: Promise<{ slug: string }>;
}

const OG_SITE_NAME = "GAIA";
const OG_IMAGE_WIDTH = 1200;
const OG_IMAGE_HEIGHT = 630;
/** The link's /meta, deduped per render by `cache`. */
const linkMeta = cache(async (slug: string) =>
  fetchLinkMeta(slug, await headers()),
);

export async function generateMetadata({
  params,
}: PageProps): Promise<Metadata> {
  const { slug } = await params;
  const reply = await linkMeta(slug);
  if (!reply) {
    return { title: OG_SITE_NAME, robots: { index: false, follow: false } };
  }
  const { meta } = reply;
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

  const resolution = await resolveLinkOnServer(slug, await headers());
  if (resolution.kind === "open") {
    return <OpenLinkView slug={slug} envelope={resolution.envelope} />;
  }
  const { state } = resolution;
  if (state.denial === "link_not_found") notFound();
  if (BROWSER_RESOLVED_DENIALS.has(state.denial)) {
    return <GatedLinkView slug={slug} />;
  }
  // The App Router answers 200 here; only notFound() can set a status.
  return <LinkUnavailable state={state} />;
}
