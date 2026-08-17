"use client";

import { Button } from "@heroui/button";
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
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-800/40 p-2.5">
      <div className="flex min-w-0 items-center gap-3">
        {faviconFailed ? (
          <div className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-zinc-900 ring-1 ring-white/5">
            <GlobalIcon className="size-4 text-zinc-500" />
          </div>
        ) : (
          <Image
            src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(login.domain)}&sz=64`}
            alt=""
            width={36}
            height={36}
            className="size-9 shrink-0 rounded-lg bg-zinc-900 object-contain p-1.5 ring-1 ring-white/5"
            unoptimized
            onError={() => setFaviconFailed(true)}
          />
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-zinc-100">
            {login.domain}
          </p>
          <p className="text-xs text-zinc-500">
            {login.updated_at
              ? `Signed in ${formatRelativeDate(login.updated_at)}`
              : "Signed in recently"}
          </p>
        </div>
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
      message: `Forget all ${logins.length} saved logins? GAIA will need to sign in again on every site.`,
      confirmText: "Continue",
      cancelText: "Cancel",
      variant: "destructive",
    });
    if (!confirmed) return;

    const doubleConfirmed = await confirm({
      title: "This cannot be undone",
      message: "Really forget every saved login?",
      confirmText: "Forget everything",
      cancelText: "Keep my logins",
      variant: "destructive",
    });
    if (!doubleConfirmed) return;

    await clearAllLogins();
  };

  return (
    <section>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-zinc-200">Saved logins</h3>
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
          <span>Couldn&apos;t load your saved logins.</span>
          <Button size="sm" variant="flat" onPress={() => void refetch()}>
            Retry
          </Button>
        </div>
      ) : logins.length === 0 ? (
        <div className="flex flex-col items-center justify-center gap-3 rounded-2xl bg-zinc-800/40 p-8 text-center">
          <div className="rounded-full bg-zinc-900 p-3">
            <GlobalIcon className="size-5 text-zinc-500" />
          </div>
          <p className="text-sm text-zinc-400">No saved logins yet</p>
          <p className="max-w-xs text-xs text-zinc-500">
            When GAIA signs in somewhere for you, that site appears here so you
            can review or forget it.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2">
          {logins.map((login) => (
            <LoginRow
              key={login.domain}
              login={login}
              onForget={forgetLogin}
              isForgetting={forgettingDomain === login.domain}
            />
          ))}
        </div>
      )}

      <ConfirmationDialog {...confirmationProps} />
    </section>
  );
}
