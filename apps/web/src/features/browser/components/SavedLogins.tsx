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
    <div className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-800/50 p-3">
      <div className="flex min-w-0 items-center gap-3">
        {faviconFailed ? (
          <div className="flex size-8 shrink-0 items-center justify-center rounded-full bg-zinc-900">
            <GlobalIcon className="size-4 text-zinc-500" />
          </div>
        ) : (
          <Image
            src={`https://www.google.com/s2/favicons?domain=${encodeURIComponent(login.domain)}&sz=64`}
            alt=""
            width={32}
            height={32}
            className="size-8 shrink-0 rounded-full bg-zinc-900 object-contain p-1.5"
            unoptimized
            onError={() => setFaviconFailed(true)}
          />
        )}
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-zinc-200">
            {login.domain}
          </p>
          <p className="text-xs text-zinc-500">
            {login.updated_at
              ? `Updated ${formatRelativeDate(login.updated_at)}`
              : "Updated recently"}
          </p>
        </div>
      </div>
      <Button
        size="sm"
        variant="flat"
        color="danger"
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
      message: `Permanently forget all ${logins.length} saved logins? GAIA will need to sign in again on every site.`,
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

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <Skeleton className="h-14 w-full rounded-2xl" />
        <Skeleton className="h-14 w-full rounded-2xl" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center gap-3 rounded-2xl bg-zinc-800 p-6 text-center text-sm text-zinc-400">
        <span>Couldn&apos;t load your saved logins.</span>
        <Button size="sm" variant="flat" onPress={() => void refetch()}>
          Retry
        </Button>
      </div>
    );
  }

  if (logins.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 rounded-2xl bg-zinc-800 p-6 text-center">
        <div className="rounded-full bg-zinc-900 p-3">
          <GlobalIcon className="size-5 text-zinc-500" />
        </div>
        <p className="text-sm text-zinc-400">No saved logins yet</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-end">
        <Button
          size="sm"
          color="danger"
          variant="flat"
          isLoading={isClearingAll}
          onPress={() => void handleClearAll()}
        >
          Clear all
        </Button>
      </div>
      <div className="flex flex-col gap-3">
        {logins.map((login) => (
          <LoginRow
            key={login.domain}
            login={login}
            onForget={forgetLogin}
            isForgetting={forgettingDomain === login.domain}
          />
        ))}
      </div>
      <ConfirmationDialog {...confirmationProps} />
    </div>
  );
}
