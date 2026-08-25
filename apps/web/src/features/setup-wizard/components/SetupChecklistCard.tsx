/**
 * Dismissible checklist card shown on the chat empty state until the
 * instance's essentials are configured (AI provider, web search, admin
 * account). Each row deep-links to where it can be fixed. Dismissal records
 * WHICH items were pending and only hides those — if the instance slips back
 * into an unconfigured state later (e.g. the LLM key is removed), the card
 * re-arms and shows again. Renders nothing while loading or on error — it
 * must never block or clutter an already-working chat.
 */

"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon, Cancel01Icon } from "@icons";
import * as m from "motion/react-m";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { LLM_PROVIDER_KEYS } from "@/features/settings/api/providersApi";
import {
  isProviderConfigured,
  useSetupStatus,
} from "@/features/settings/hooks/useSetupStatus";

const DISMISSED_KEY = "gaia_setup_checklist_dismissed";

interface ChecklistItem {
  key: string;
  title: string;
  description: string;
  href: string;
}

/** Item keys pending when the checklist was last dismissed (localStorage).
 * A missing/legacy/unparsable value reads as nothing-dismissed so the card
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

export function SetupChecklistCard() {
  const { data: status } = useSetupStatus();
  const [dismissedKeys, setDismissedKeys] = useState<string[]>([]);

  // Read localStorage after mount so SSR and hydration agree.
  useEffect(() => {
    setDismissedKeys(readDismissedSnapshot());
  }, []);

  const items = useMemo<ChecklistItem[]>(() => {
    if (!status) return [];
    const list: ChecklistItem[] = [];
    const hasLlm = LLM_PROVIDER_KEYS.some((key) =>
      isProviderConfigured(status, key),
    );
    if (!hasLlm) {
      list.push({
        key: "llm",
        title: "Connect an AI provider",
        description: "Add a key or point at Ollama to start chatting.",
        href: "/setup",
      });
    }
    if (!isProviderConfigured(status, "tavily")) {
      list.push({
        key: "search",
        title: "Enable web search",
        description: "A Tavily key lets GAIA search the live web.",
        href: "/settings/providers",
      });
    }
    if (!status.has_admin_account) {
      list.push({
        key: "admin",
        title: "Create the admin account",
        description: "Secure your instance with its administrator login.",
        href: "/signup",
      });
    }
    return list;
  }, [status]);

  // Hidden only while the pending set matches what was dismissed; any new or
  // returning item (LLM unconfigured again) makes the card visible once more.
  const isDismissed =
    items.length > 0 &&
    dismissedKeys.length === items.length &&
    items.every((item) => dismissedKeys.includes(item.key));

  if (!status || items.length === 0 || isDismissed) return null;

  const handleDismiss = () => {
    const keys = items.map((item) => item.key);
    setDismissedKeys(keys);
    try {
      window.localStorage.setItem(DISMISSED_KEY, JSON.stringify(keys));
    } catch {
      // Same as above — non-persistent dismissal is fine.
    }
  };

  return (
    <m.div
      className="mt-5 w-full max-w-lg"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
    >
      <div className="w-full rounded-2xl bg-zinc-800 p-4">
        <div className="mb-3 flex items-center justify-between gap-2">
          <p className="text-sm font-semibold text-zinc-100">
            Finish setting up your instance
          </p>
          <Button
            isIconOnly
            size="sm"
            variant="light"
            radius="full"
            aria-label="Dismiss setup checklist"
            onPress={handleDismiss}
            className="text-zinc-500"
          >
            <Cancel01Icon size={14} />
          </Button>
        </div>
        <div className="space-y-2">
          {items.map((item) => (
            <Link
              key={item.key}
              href={item.href}
              className="flex items-center justify-between gap-3 rounded-2xl bg-zinc-900 p-3 transition-all duration-200 hover:bg-zinc-700"
            >
              <span className="min-w-0 flex-col">
                <span className="block truncate text-sm font-medium text-zinc-200">
                  {item.title}
                </span>
                <span className="block truncate text-xs text-zinc-500">
                  {item.description}
                </span>
              </span>
              <ArrowRight02Icon
                height={16}
                className="shrink-0 text-zinc-500"
              />
            </Link>
          ))}
        </div>
      </div>
    </m.div>
  );
}
