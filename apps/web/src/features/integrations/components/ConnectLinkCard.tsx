"use client";

import { Skeleton } from "@heroui/react";

import { RaisedButton } from "@/components/ui/raised-button";

import { useConnectLinkPreview } from "../hooks/useConnectLinkPreview";
import { ConnectLinkExpired } from "./ConnectLinkExpired";
import { ConnectLinkLogos } from "./ConnectLinkLogos";

interface ConnectLinkCardProps {
  code: string;
  action: string;
}

/**
 * The Continue form for a bot connect link, headed by what it connects and for
 * which account. Only Continue spends the code; the preview never does.
 */
export function ConnectLinkCard({ code, action }: ConnectLinkCardProps) {
  const state = useConnectLinkPreview(code);

  if (state.kind === "expired") {
    return <ConnectLinkExpired />;
  }

  const preview = state.kind === "ready" ? state.preview : null;
  return (
    <form method="post" action={action}>
      <input type="hidden" name="code" value={code} />
      {state.kind === "loading" ? (
        <Skeleton className="mx-auto mb-6 h-16 w-40 rounded-2xl" />
      ) : (
        preview && <ConnectLinkLogos preview={preview} />
      )}
      <h1 className="mb-2 text-xl font-semibold text-white">
        {preview
          ? `Connect ${preview.integration_name} to GAIA`
          : "Connect your integration"}
      </h1>
      {preview?.account_email && (
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
        {preview ? `Continue to ${preview.integration_name}` : "Continue"}
      </RaisedButton>
    </form>
  );
}
