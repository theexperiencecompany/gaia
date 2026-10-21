import { renderInviteOgImage } from "@/app/api/og/invite/inviteOgImage";
import { createFallbackResponse, OG_HEIGHT, OG_WIDTH } from "@/app/api/og/lib";
import { resolveInviteServer } from "@/features/referrals/lib/serverReferralsApi";
import { INVITE_OG_VARIANT } from "@/features/referrals/referralCopy";
import { siteConfig } from "@/lib/seo";

export const size = { width: OG_WIDTH, height: OG_HEIGHT };
export const contentType = "image/png";
export const alt = "An invite to GAIA";

interface InviteOgImageProps {
  params: Promise<{ code: string }>;
}

export default async function InviteOgImage({ params }: InviteOgImageProps) {
  const { code } = await params;
  const invite = await resolveInviteServer(code);
  if (!invite?.valid) return createFallbackResponse(siteConfig.name);
  return renderInviteOgImage({
    invite,
    code,
    copyVariant: INVITE_OG_VARIANT,
    baseUrl: siteConfig.url,
  });
}
