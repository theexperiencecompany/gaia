/**
 * Slim dismissible banner at the top of the chat home until the instance's
 * essentials are configured (AI provider, web search, admin account). One
 * missing item is one line with its action; several collapse into a single
 * line that expands to one row per item. Dismissal records WHICH items were
 * pending and only hides those, so the banner re-arms if the instance slips
 * back into an unconfigured state. Renders nothing while loading or on error.
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
  isChecklistDismissed,
  type SetupChecklistItem,
} from "@/features/setup-wizard/utils/setupChecklist";
import { cn } from "@/lib/utils";

const DISMISSED_KEY = "gaia_setup_checklist_dismissed";

/** Item keys pending when the checklist was last dismissed (localStorage).
 * A missing/legacy/unparsable value reads as nothing-dismissed so the banner
 * re-arms instead of staying hidden forever. */
function readDismissedSnapshot(): string[] {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((key): key is string => typeof key === "string");
  } catch {
    // localStorage unavailable (private mode) — never treat as dismissed.
    return [];
  }
}

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
  // Instance setup is the admin's job; a member could not act on any item.
  const isMember = useCurrentUser().role === "member";
  const [dismissedKeys, setDismissedKeys] = useState<string[]>([]);
  const [isExpanded, setIsExpanded] = useState(false);

  // Read localStorage after mount so SSR and hydration agree.
  useEffect(() => {
    setDismissedKeys(readDismissedSnapshot());
  }, []);

  const items = useMemo(
    () => (status && catalog ? buildSetupChecklist(status, catalog) : []),
    [status, catalog],
  );

  if (
    isMember ||
    items.length === 0 ||
    isChecklistDismissed(items, dismissedKeys)
  )
    return null;

  const handleDismiss = () => {
    const keys = items.map((item) => item.key);
    setDismissedKeys(keys);
    try {
      window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(keys));
    } catch {
      // Same as above — non-persistent dismissal is fine.
    }
  };

  const [onlyItem] = items;
  const isSingle = items.length === 1;

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
                {items.length} setup steps left
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
          <Button
            isIconOnly
            size="sm"
            variant="light"
            radius="full"
            aria-label="Dismiss setup checklist"
            onPress={handleDismiss}
            className="shrink-0 text-zinc-500"
          >
            <Cancel01Icon size={14} />
          </Button>
        </div>
        {!isSingle && isExpanded && (
          <ul className="mt-2 space-y-1.5">
            {items.map((item) => (
              <li
                key={item.key}
                className="flex items-center rounded-xl bg-zinc-900 py-1.5 pr-1.5 pl-3"
              >
                <ChecklistLine item={item} />
              </li>
            ))}
          </ul>
        )}
      </div>
    </m.div>
  );
}
