"use client";

import { Spinner } from "@heroui/spinner";
import { Link01Icon } from "@icons";
import Image from "next/image";
import { RedirectType, redirect } from "next/navigation";

import { RaisedButton } from "@/components/ui/raised-button";
import { useLinkPlatform } from "@/features/auth/hooks/useLinkPlatform";

import { LinkCard } from "./LinkCard";
import { InvalidLinkCard, LinkedSuccessCard } from "./LinkPlatformStates";

interface LinkPlatformClientProps {
  platform: string | null;
  token: string | null;
}

export default function LinkPlatformClient({
  platform,
  token,
}: Readonly<LinkPlatformClientProps>) {
  const {
    isAuthenticated,
    hasHydrated,
    config,
    accountInfo,
    error,
    isLinking,
    isLinked,
    handleLink,
  } = useLinkPlatform(platform, token);

  if (!token || !platform || !config) {
    return <InvalidLinkCard />;
  }

  if (!hasHydrated) {
    return null;
  }

  // Unauthenticated once the cache has restored — go sign in and come back.
  // Resolved during render (not in an effect) so this page never paints before
  // navigating; `redirect` performs the same client-side navigation
  // router.replace did.
  if (!isAuthenticated) {
    const returnUrl = `/auth/link-platform?platform=${encodeURIComponent(platform)}&token=${encodeURIComponent(token)}`;
    redirect(
      `/login?return_url=${encodeURIComponent(returnUrl)}`,
      RedirectType.replace,
    );
  }

  if (isLinked) {
    return <LinkedSuccessCard platformName={config.name} />;
  }

  return (
    <LinkCard>
      <Image
        src={config.iconSrc}
        alt={`${config.name} icon`}
        width={64}
        height={64}
        className="mx-auto mb-5 h-16 w-16"
      />
      <h2 className="mb-2 text-xl font-semibold text-white">
        Connect {config.name} to GAIA
      </h2>
      {(accountInfo?.displayName || accountInfo?.username) && (
        <p className="mb-1 text-sm font-medium text-zinc-300">
          {accountInfo.displayName ?? accountInfo.username}
          {accountInfo.username && accountInfo.displayName ? (
            <span className="ml-1 text-zinc-500">@{accountInfo.username}</span>
          ) : null}
        </p>
      )}
      <p className="mb-6 text-sm text-zinc-400">
        Chat with GAIA, your personal AI assistant, right inside {config.name}.
        Fully synced with your account.
      </p>

      {error && <p className="mb-4 text-sm text-red-400">{error}</p>}

      <RaisedButton
        size="lg"
        color="#00bbff"
        className="w-full font-medium text-black!"
        onClick={handleLink}
        disabled={isLinking}
      >
        {isLinking ? (
          <Spinner size="sm" color="default" />
        ) : (
          <Link01Icon className="h-5 w-5" />
        )}
        Connect {config.name}
      </RaisedButton>
    </LinkCard>
  );
}
