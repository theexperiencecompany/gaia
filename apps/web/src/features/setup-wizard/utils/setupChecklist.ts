import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { isAnyLlmConfigured } from "@/features/settings/hooks/useSetupStatus";

type SetupChecklistKey = "llm" | "admin";

export interface SetupChecklistItem {
  key: SetupChecklistKey;
  title: string;
  description: string;
  actionLabel: string;
  href: string;
}

/** The instance essentials still missing, in the order an admin should fix them. */
export function buildSetupChecklist(
  status: SetupStatus,
  catalog: ProviderCatalog,
): SetupChecklistItem[] {
  const items: SetupChecklistItem[] = [];
  if (!isAnyLlmConfigured(status, catalog)) {
    items.push({
      key: "llm",
      title: "Connect an AI provider",
      description: "Add a key or use local Ollama to start chatting.",
      actionLabel: "Connect",
      href: "/setup",
    });
  }
  if (!status.has_admin_account) {
    items.push({
      key: "admin",
      title: "Create the admin account",
      description: "Protect this setup with a login only you control.",
      actionLabel: "Create",
      href: "/signup",
    });
  }
  return items;
}

/** Hidden only while the pending set matches what was dismissed; any new or
 * returning item (LLM unconfigured again) re-arms the checklist. */
export function isChecklistDismissed(
  items: SetupChecklistItem[],
  dismissedKeys: string[],
): boolean {
  const dismissed = new Set(dismissedKeys);
  return (
    items.length > 0 &&
    dismissed.size === items.length &&
    items.every((item) => dismissed.has(item.key))
  );
}
