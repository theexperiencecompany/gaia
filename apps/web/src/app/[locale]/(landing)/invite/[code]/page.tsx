import type { Metadata } from "next";
import { OG_HEIGHT, OG_WIDTH } from "@/app/api/og/lib";
import { InviteLandingPage } from "@/features/referrals/components/InviteLandingPage";
import { resolveInviteServer } from "@/features/referrals/lib/serverReferralsApi";
import {
  INVITE_OG_VARIANT,
  REFERRAL_COPY,
} from "@/features/referrals/referralCopy";
import { offerPrices } from "@/features/referrals/utils/offerPrices";
import { siteConfig } from "@/lib/seo";

const INVITE_OG_ALT = "An invite to GAIA";

interface InvitePageProps {
  params: Promise<{ code: string }>;
}

export async function generateMetadata({
  params,
}: InvitePageProps): Promise<Metadata> {
  const { code } = await params;
  const invite = await resolveInviteServer(code);
  const { og } = REFERRAL_COPY[INVITE_OG_VARIANT];
  const title =
    invite?.valid && invite.referrer_first_name
      ? og.title(invite.referrer_first_name)
      : siteConfig.name;
  const description = invite
    ? og.subtitle(offerPrices(invite.offer))
    : siteConfig.description;
  const image = {
    url: `/api/og/invite/${code}`,
    width: OG_WIDTH,
    height: OG_HEIGHT,
    alt: INVITE_OG_ALT,
    type: "image/png",
  };
  // One page per referrer: shareable previews, never search results.
  return {
    title,
    description,
    robots: { index: false, follow: true },
    alternates: { canonical: `${siteConfig.url}/invite/${code}` },
    openGraph: {
      title,
      description,
      url: `${siteConfig.url}/invite/${code}`,
      images: [image],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [image],
    },
  };
}

export default async function InvitePage({ params }: InvitePageProps) {
  const { code } = await params;
  return <InviteLandingPage code={code} />;
}
