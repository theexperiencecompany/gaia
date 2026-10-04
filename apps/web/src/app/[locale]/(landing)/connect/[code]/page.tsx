import { ConnectIcon } from "@icons";
import type { Metadata } from "next";

import { RaisedButton } from "@/components/ui/raised-button";
import { generatePageMetadata } from "@/lib/seo";

export const metadata: Metadata = {
  ...generatePageMetadata({
    title: "Connect an integration",
    description:
      "Continue to connect an integration to your GAIA account from a link GAIA sent you.",
    path: "/connect",
    noIndex: true,
  }),
  // The code is in this page's URL; keep it out of the provider's Referer.
  referrer: "no-referrer",
};

interface ConnectLinkPageProps {
  params: Promise<{ code: string }>;
}

/**
 * Landing for the single-use connect links bots send. Spending the code takes
 * a button press (a form POST), because link-preview crawlers GET every link
 * in a chat and would otherwise burn it before the user taps.
 */
export default async function ConnectLinkPage({
  params,
}: Readonly<ConnectLinkPageProps>) {
  const { code } = await params;
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  if (!apiBaseUrl) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL is not set");
  }
  const action = `${apiBaseUrl.replace(/\/+$/, "")}/integrations/connect-link`;

  return (
    <div className="flex min-h-[70vh] items-center justify-center p-4">
      <form
        method="post"
        action={action}
        className="w-full max-w-md rounded-3xl bg-zinc-900 p-8 text-center"
      >
        <input type="hidden" name="code" value={code} />
        <ConnectIcon className="mx-auto mb-5 h-12 w-12 text-primary" />
        <h1 className="mb-2 text-xl font-semibold text-white">
          Connect your integration
        </h1>
        <p className="mb-6 text-sm text-zinc-400">
          GAIA sent you this link to connect an account. It works once and
          expires an hour after it was sent.
        </p>
        <RaisedButton
          type="submit"
          size="lg"
          color="#00bbff"
          className="w-full font-medium text-black!"
        >
          Continue
        </RaisedButton>
      </form>
    </div>
  );
}
