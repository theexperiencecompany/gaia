"use client";

import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Input } from "@heroui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { ScrollShadow } from "@heroui/react";
import { Skeleton } from "@heroui/skeleton";
import {
  ArcBrowserIcon,
  ChromeIcon,
  Clock01Icon,
  Delete02Icon,
  EdgeStyleIcon,
  GlobalIcon,
  Location01Icon,
  SafariIcon,
  Search01Icon,
} from "@icons";
import Image from "next/image";
import { type ComponentType, useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import { useConfirmation } from "@/hooks/useConfirmation";
import { useBrowserLogins } from "../hooks/useBrowserLogins";
import type { SavedBrowserLogin } from "../types";
import { formatRelativeDate } from "../utils";

/** Source value stamped on logins the `gaia connect` CLI imported. */
const IMPORT_SOURCE = "import";

/** Real browser logo for a source name, falling back to a globe. */
function browserIcon(
  name: string | null,
): ComponentType<{ className?: string }> {
  switch (name?.toLowerCase()) {
    case "arc":
      return ArcBrowserIcon;
    case "chrome":
      return ChromeIcon;
    case "edge":
      return EdgeStyleIcon;
    case "safari":
      return SafariIcon;
    default:
      return GlobalIcon;
  }
}

function ProvenanceFact({
  icon: Icon,
  heading,
  value,
}: {
  icon: ComponentType<{ className?: string }>;
  heading: string;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3">
      <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-zinc-800">
        <Icon className="size-4 text-zinc-400" />
      </div>
      <div className="min-w-0">
        <p className="text-xs text-zinc-500">{heading}</p>
        <p className="truncate text-sm text-zinc-200">{value}</p>
      </div>
    </div>
  );
}

/** "Imported" chip that reveals where/when the login was imported on hover. */
function ImportedBadge({ login }: { login: SavedBrowserLogin }) {
  const [open, setOpen] = useState(false);
  const BrowserLogo = browserIcon(login.source_browser);

  return (
    <Popover isOpen={open} onOpenChange={setOpen} placement="top" showArrow>
      <PopoverTrigger>
        <button
          type="button"
          onMouseEnter={() => setOpen(true)}
          onMouseLeave={() => setOpen(false)}
        >
          <Chip size="sm" variant="flat" className="bg-zinc-800 text-zinc-300">
            Imported
          </Chip>
        </button>
      </PopoverTrigger>
      <PopoverContent className="rounded-2xl bg-zinc-900 p-3">
        <div className="flex flex-col gap-3">
          {login.source_browser && (
            <ProvenanceFact
              icon={BrowserLogo}
              heading="Browser"
              value={login.source_browser}
            />
          )}
          {login.source_ip && (
            <ProvenanceFact
              icon={Location01Icon}
              heading="IP address"
              value={login.source_ip}
            />
          )}
          {login.updated_at && (
            <ProvenanceFact
              icon={Clock01Icon}
              heading="Imported"
              value={formatRelativeDate(login.updated_at)}
            />
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** "Expires in 42 days" countdown to the TTL; `soon` flags the last week. */
function expiresIn(
  expiresAt: string | null,
): { text: string; soon: boolean } | null {
  if (!expiresAt) return null;
  const days = Math.ceil(
    (new Date(expiresAt).getTime() - Date.now()) / 86_400_000,
  );
  if (days <= 0) return { text: "Expired", soon: true };
  if (days === 1) return { text: "Expires tomorrow", soon: true };
  return { text: `Expires in ${days} days`, soon: days <= 7 };
}

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
  const exp = expiresIn(login.expires_at);

  return (
    <div className="group flex items-center justify-between gap-3 rounded-2xl bg-zinc-800/40 p-3">
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
          {login.source === IMPORT_SOURCE && <ImportedBadge login={login} />}
        </div>
        {exp && (
          <p
            className={`mt-0.5 text-xs ${exp.soon ? "text-amber-400/80" : "text-zinc-500"}`}
          >
            {exp.text}
          </p>
        )}
      </div>
      <Button
        size="sm"
        variant="light"
        color="danger"
        className={`h-8 shrink-0 transition-opacity ${isForgetting ? "opacity-100" : "opacity-0 group-hover:opacity-100"}`}
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
  const [query, setQuery] = useState("");
  const filtered = query.trim()
    ? logins.filter((l) => l.domain.includes(query.trim().toLowerCase()))
    : logins;

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

      {logins.length > 0 && (
        <Input
          size="sm"
          radius="lg"
          value={query}
          onValueChange={setQuery}
          isClearable
          onClear={() => setQuery("")}
          placeholder="Search saved sites…"
          startContent={<Search01Icon className="size-4 text-zinc-500" />}
          className="mb-2"
          classNames={{ inputWrapper: "bg-zinc-800" }}
        />
      )}

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
            {filtered.length === 0 ? (
              <p className="py-6 text-center text-xs text-zinc-500">
                No saved sites match &ldquo;{query}&rdquo;.
              </p>
            ) : null}
            {filtered.map((login) => (
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
