/**
 * Slim banner at the top of the chat home listing what is left to configure:
 * the required items, then each optional feature that is still off. One item
 * is one line with its action; several collapse into a single line that
 * expands to one row per item. Each item can be dismissed on its own, and a
 * dismissal lapses once the item is done, so one that comes back shows again.
 * Renders nothing while loading or on error.
 */

"use client";

import { Button } from "@heroui/button";
import { ArrowDown01Icon, Cancel01Icon, Wrench01Icon } from "@icons";
import * as m from "motion/react-m";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";
import {
  buildSetupChecklist,
  type SetupChecklistItem,
  visibleChecklistItems,
} from "@/features/setup-wizard/utils/setupChecklist";
import { cn } from "@/lib/utils";
import { useSetupChecklistStore } from "@/stores/setupChecklistStore";

function ChecklistAction({ item }: { item: SetupChecklistItem }) {
  return (
    <Button
      as={Link}
      href={item.href}
      size="sm"
      variant="flat"
      className="shrink-0 font-medium"
    >
      {item.actionLabel}
    </Button>
  );
}

function DismissButton({
  label,
  onDismiss,
}: {
  label: string;
  onDismiss: () => void;
}) {
  return (
    <Button
      isIconOnly
      size="sm"
      variant="light"
      radius="full"
      aria-label={label}
      onPress={onDismiss}
      className="shrink-0 text-zinc-500"
    >
      <Cancel01Icon size={14} />
    </Button>
  );
}

function ChecklistLine({ item }: { item: SetupChecklistItem }) {
  return (
    <div className="flex min-w-0 flex-1 items-center gap-3">
      <p className="min-w-0 flex-1 truncate text-xs">
        <span className="font-medium text-zinc-200">{item.title}</span>
        <span className="hidden text-zinc-500 sm:inline">
          {" "}
          {item.description}
        </span>
      </p>
      <ChecklistAction item={item} />
    </div>
  );
}

interface SetupChecklistBannerProps {
  className?: string;
}

export function SetupChecklistBanner({
  className,
}: SetupChecklistBannerProps = {}) {
  const { data: status } = useSetupStatus();
  const { data: catalog } = useProviderCatalog();
  // Instance setup is the admin's job; nobody else (or an unknown role) sees it.
  const isAdmin = useCurrentUser().role === "admin";
  const dismissedKeys = useSetupChecklistStore((s) => s.dismissedKeys);
  const dismiss = useSetupChecklistStore((s) => s.dismiss);
  const keepPending = useSetupChecklistStore((s) => s.keepPending);
  const [isExpanded, setIsExpanded] = useState(false);

  const items = useMemo(
    () => (status && catalog ? buildSetupChecklist(status, catalog) : null),
    [status, catalog],
  );

  useEffect(() => {
    if (items) keepPending(items.map((item) => item.key));
  }, [items, keepPending]);

  if (!isAdmin || !items) return null;
  const visible = visibleChecklistItems(items, dismissedKeys);
  if (visible.length === 0) return null;

  const [onlyItem] = visible;
  const isSingle = visible.length === 1;

  return (
    <m.div
      className={cn("flex w-full justify-center", className)}
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
    >
      <div className="w-full max-w-2xl rounded-2xl bg-zinc-800 px-3 py-2">
        <div className="flex items-center gap-3">
          <Wrench01Icon size={16} className="shrink-0 text-zinc-400" />
          {isSingle ? (
            <ChecklistLine item={onlyItem} />
          ) : (
            <div className="flex min-w-0 flex-1 items-center gap-3">
              <p className="min-w-0 flex-1 truncate text-xs font-medium text-zinc-200">
                {visible.length} setup steps left
              </p>
              <Button
                size="sm"
                variant="flat"
                className="shrink-0 font-medium"
                aria-expanded={isExpanded}
                endContent={
                  <ArrowDown01Icon
                    size={14}
                    className={cn(
                      "transition-transform duration-200",
                      isExpanded && "rotate-180",
                    )}
                  />
                }
                onPress={() => setIsExpanded((open) => !open)}
              >
                {isExpanded ? "Hide" : "Show"}
              </Button>
            </div>
          )}
          <DismissButton
            label="Dismiss setup checklist"
            onDismiss={() => dismiss(visible.map((item) => item.key))}
          />
        </div>
        {!isSingle && isExpanded && (
          <ul className="mt-2 space-y-1.5">
            {visible.map((item) => (
              <li
                key={item.key}
                className="flex items-center gap-1 rounded-xl bg-zinc-900 py-1.5 pr-1.5 pl-3"
              >
                <ChecklistLine item={item} />
                <DismissButton
                  label={`Dismiss ${item.title}`}
                  onDismiss={() => dismiss([item.key])}
                />
              </li>
            ))}
          </ul>
        )}
      </div>
    </m.div>
  );
}
