"use client";

import { Button } from "@heroui/button";
import { ScrollShadow } from "@heroui/react";
import { Skeleton } from "@heroui/skeleton";
import { Delete02Icon, GlobalIcon } from "@icons";
import Image from "next/image";
import { useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useConfirmation } from "@/hooks/useConfirmation";
import { useBrowserLogins } from "../hooks/useBrowserLogins";
import type { SavedBrowserLogin } from "../types";
import { formatRelativeDate } from "../utils";

function LoginRow({
  login,
  onForget,
  isForgetting,
}: {
  login: SavedBrowserLogin;
  onForget: (domain: string) => void;
  isForgetting: boolean;
}) {
  const [faviconFailed, setFaviconFailed] = useState(false);

  return (
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-800/40 p-3">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          {faviconFailed ? (
            <GlobalIcon className="size-4 shrink-0 text-zinc-500" />
          ) : (
            <Image
              src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(login.domain)}&sz=64`}
              alt=""
              width={32}
              height={32}
              className="size-4 shrink-0 rounded-full object-cover"
              unoptimized
              onError={() => setFaviconFailed(true)}
            />
          )}
          <span className="truncate text-sm font-medium text-zinc-100">
            {login.domain}
          </span>
        </div>
        <p className="mt-0.5 text-xs text-zinc-500">
          {login.updated_at
            ? `Saved ${formatRelativeDate(login.updated_at)}`
            : "Saved recently"}
        </p>
      </div>
      <Button
        size="sm"
        variant="light"
        color="danger"
        className="h-8"
        isLoading={isForgetting}
        startContent={!isForgetting && <Delete02Icon className="size-4" />}
        onPress={() => onForget(login.domain)}
      >
        Forget
      </Button>
    </div>
  );
}

export function SavedLogins() {
  const {
    logins,
    isLoading,
    error,
    refetch,
    forgetLogin,
    forgettingDomain,
    clearAllLogins,
    isClearingAll,
  } = useBrowserLogins();
  const { confirm, confirmationProps } = useConfirmation();

  const handleClearAll = async () => {
    const confirmed = await confirm({
      title: "Clear all saved logins",
      message: `Forget all ${logins.length} saved sites? GAIA will start fresh on each and need to sign in again where you'd logged in.`,
      confirmText: "Continue",
      cancelText: "Cancel",
      variant: "destructive",
    });
    if (!confirmed) return;

    const doubleConfirmed = await confirm({
      title: "This cannot be undone",
      message: "Really forget every saved site?",
      confirmText: "Forget everything",
      cancelText: "Keep them",
      variant: "destructive",
    });
    if (!doubleConfirmed) return;

    await clearAllLogins();
  };

  return (
    <section>
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-zinc-200">Saved sites</h3>
          <p className="mt-0.5 text-xs text-zinc-500">
            Encrypted session data GAIA keeps for sites it visits, so it stays
            signed in where you've logged in.
          </p>
        </div>
        {logins.length > 0 && (
          <Button
            size="sm"
            color="danger"
            variant="light"
            className="h-7"
            isLoading={isClearingAll}
            onPress={() => void handleClearAll()}
          >
            Clear all
          </Button>
        )}
      </div>

      {isLoading ? (
        <div className="flex flex-col gap-2">
          <Skeleton className="h-14 w-full rounded-2xl" />
          <Skeleton className="h-14 w-full rounded-2xl" />
        </div>
      ) : error ? (
        <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-800/40 p-6 text-center text-sm text-zinc-400">
          <span>Couldn&apos;t load your saved sites.</span>
          <Button size="sm" variant="flat" onPress={() => void refetch()}>
            Retry
          </Button>
        </div>
      ) : logins.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-2xl bg-zinc-800/40 p-8 text-center">
          <div className="rounded-full bg-zinc-900 p-3">
            <GlobalIcon className="size-5 text-zinc-500" />
          </div>
          <p className="text-sm text-zinc-400">Nothing saved yet</p>
          <p className="max-w-xs text-xs text-zinc-500">
            As GAIA browses on your behalf, the sites it visits appear here so
            you can review or forget them.
          </p>
        </div>
      ) : (
        <ScrollShadow className="max-h-[540px]">
          <div className="flex flex-col gap-2 pr-1">
            {logins.map((login) => (
              <LoginRow
                key={login.domain}
                login={login}
                onForget={forgetLogin}
                isForgetting={forgettingDomain === login.domain}
              />
            ))}
          </div>
        </ScrollShadow>
      )}

      <ConfirmationDialog {...confirmationProps} />
    </section>
  );
}
