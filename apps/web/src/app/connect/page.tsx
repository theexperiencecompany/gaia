import type { Metadata } from "next";
import { cookies } from "next/headers";

import { ConnectLinkCard } from "@/features/integrations/components/ConnectLinkCard";
import { ConnectLinkExpired } from "@/features/integrations/components/ConnectLinkExpired";
import { CONNECT_LINK_COOKIE } from "@/features/integrations/constants/connect";
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
 * /connect/<code>, and is spent only when the user presses Continue.
 */
export default async function ConnectLinkPage() {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!apiBaseUrl) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");
  }
  const code = (await cookies()).get(CONNECT_LINK_COOKIE)?.value;
  const action = `${apiBaseUrl.replace(/\/+$/, "")}/integrations/connect-link`;

  return (
    <div className="flex min-h-screen items-center justify-center bg-black p-4">
      <div className="w-full max-w-md rounded-3xl bg-zinc-900 p-8 text-center">
        {code ? (
          <ConnectLinkCard code={code} action={action} />
        ) : (
          <ConnectLinkExpired />
        )}
      </div>
    </div>
  );
}
