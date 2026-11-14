import { renderInviteOgImage } from "@/app/api/og/invite/inviteOgImage";
import { createFallbackResponse } from "@/app/api/og/lib";
import { resolveInviteServer } from "@/features/referrals/lib/serverReferralsApi";
import { INVITE_OG_VARIANT } from "@/features/referrals/referralCopy";
import { siteConfig } from "@/lib/seo";

interface InviteOgImageContext {
  params: Promise<{ code: string }>;
}

/** Outside [locale], so the og:image URL answers the PNG directly instead of a locale redirect. */
export async function GET(_request: Request, { params }: InviteOgImageContext) {
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
