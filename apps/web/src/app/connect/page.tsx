import type { Metadata } from "next";
import { cookies, headers } from "next/headers";

import { RaisedButton } from "@/components/ui/raised-button";
import { ConnectLinkLogos } from "@/features/integrations/components/ConnectLinkLogos";
import {
  CONNECT_LINK_COOKIE,
  CONNECT_LINK_ERROR_MESSAGES,
} from "@/features/integrations/constants/connect";
import { fetchConnectLinkPreview } from "@/features/integrations/utils/connectLinkServerApi";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = generatePageMetadata({
  title: "Connect an integration",
  description:
    "Continue to connect an integration to your GAIA account from a link GAIA sent you.",
  path: "/connect",
  noIndex: true,
});

/**
 * The Continue step for a bot connect link. The code arrives in a cookie set by
 * /connect/<code>, is previewed (what it connects, for which account) without
 * being spent, and is spent only when the user presses Continue.
 */
export default async function ConnectLinkPage() {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!apiBaseUrl) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");
  }
  const code = (await cookies()).get(CONNECT_LINK_COOKIE)?.value;
  const preview = code
    ? await fetchConnectLinkPreview(code, await headers())
    : null;
  const action = `${apiBaseUrl.replace(/\/+$/, "")}/integrations/connect-link`;

  return (
    <div className="flex min-h-screen items-center justify-center bg-black p-4">
      <div className="w-full max-w-md rounded-3xl bg-zinc-900 p-8 text-center">
        {code && preview ? (
          <form method="post" action={action}>
            <input type="hidden" name="code" value={code} />
            <ConnectLinkLogos
              integrationId={preview.integration_id}
              iconUrl={preview.icon_url}
            />
            <h1 className="mb-2 text-xl font-semibold text-white">
              Connect {preview.name} to GAIA
            </h1>
            {preview.account_email && (
              <p className="mb-4 text-sm text-zinc-300">
                For your GAIA account{" "}
                <span className="font-medium text-white">
                  {preview.account_email}
                </span>
              </p>
            )}
            <p className="mb-6 text-sm text-zinc-500">
              This link works once and expires an hour after it was sent.
            </p>
            <RaisedButton
              type="submit"
              size="lg"
              color="#00bbff"
              className="w-full font-medium"
            >
              Continue to {preview.name}
            </RaisedButton>
          </form>
        ) : (
          <>
            <h1 className="mb-2 text-xl font-semibold text-white">
              Connect your integration
            </h1>
            <p className="text-sm text-zinc-400">
              {CONNECT_LINK_ERROR_MESSAGES.invalid_or_expired_link}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
