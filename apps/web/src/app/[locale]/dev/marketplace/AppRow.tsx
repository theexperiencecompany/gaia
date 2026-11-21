"use client";

import { LinkButton } from "@/components/shared/LinkButton";
import { IntegrationIcon } from "@/features/integrations/components/IntegrationIcon";
import { CONNECTED_APPS } from "../explore/templateModel";
import { type App, isByGaia, MARKETPLACE_PATH } from "./appModel";

/** An app in the marketplace list: its logo, its name, one line of what it is. */
export function AppRow({ app }: { app: App }) {
  const isConnected = CONNECTED_APPS.includes(app.integrationId);
  return (
    <li className="relative">
      <LinkButton
        href={`${MARKETPLACE_PATH}/${app.slug}`}
        aria-label={app.name}
        variant="row"
        shape="md"
        inset="none"
        className="absolute inset-0 h-full w-full min-w-0"
      />
      <div className="pointer-events-none relative flex gap-3.5 px-2 py-2.5">
        <span className="flex size-7 shrink-0 -translate-y-0.5 items-center justify-center">
          <IntegrationIcon
            integrationId={app.integrationId}
            iconUrl={app.iconUrl}
            category={app.category}
            size={24}
          />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex min-h-7 min-w-0 items-center gap-2">
            <p className="truncate text-[15px] leading-6 text-zinc-100">
              {app.name}
            </p>
            {!isByGaia(app) && app.creator?.name && (
              <span className="shrink-0 truncate text-[13px] text-zinc-500">
                by {app.creator.name}
              </span>
            )}
          </div>
          <p className="text-[13px] leading-5 text-zinc-500 sm:line-clamp-2">
            {app.description}
          </p>
        </div>
        {isConnected && (
          <span className="flex h-7 shrink-0 items-center text-[13px] text-zinc-500">
            Connected
          </span>
        )}
      </div>
    </li>
  );
}
