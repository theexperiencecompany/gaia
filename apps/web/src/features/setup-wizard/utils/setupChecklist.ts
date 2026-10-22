import type { ProviderFeature } from "@shared/api/generated";
import type {
  ProviderCatalog,
  SetupStatus,
} from "@/features/settings/api/providersApi";
import { providerFeatureHref } from "@/features/settings/components/providers/providerRows";
import { isAnyLlmConfigured } from "@/features/settings/hooks/useSetupStatus";

/** Chat itself; the required AI-provider item already asks for it. */
const REQUIRED_FEATURE: ProviderFeature = "ai_models";

type SetupChecklistKey = "llm" | "admin" | ProviderFeature;

export interface SetupChecklistItem {
  key: SetupChecklistKey;
  title: string;
  description: string;
  actionLabel: string;
  href: string;
}

/** What is still left to configure: the required items first, then each optional feature this instance can run, with no free default, that is off. */
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
  // The API keys features by exactly the ProviderFeature values.
  const features = Object.entries(catalog.features) as [
    ProviderFeature,
    ProviderCatalog["features"][string],
  ][];
  for (const [feature, spec] of features) {
    if (feature === REQUIRED_FEATURE || spec.built_in) continue;
    const featureStatus = status.features[feature];
    if (!featureStatus?.available || featureStatus.working) continue;
    items.push({
      key: feature,
      title: spec.label,
      description: spec.description,
      actionLabel: "Set up",
      href: providerFeatureHref(feature),
    });
  }
  return items;
}

/** The pending items the admin has not dismissed. */
export function visibleChecklistItems(
  items: SetupChecklistItem[],
  dismissedKeys: string[],
): SetupChecklistItem[] {
  const dismissed = new Set(dismissedKeys);
  return items.filter((item) => !dismissed.has(item.key));
}
