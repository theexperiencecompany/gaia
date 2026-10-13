"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Link } from "@heroui/link";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { Spinner } from "@heroui/spinner";
import { SquareArrowUpRight02Icon, ViewIcon, ViewOffSlashIcon } from "@icons";
import Image from "next/image";
import { useEffect, useMemo, useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import {
  type CredentialProvider,
  extractProviderError,
  getProviderErrorHint,
  PROVIDER_KEY_URLS,
  type ProviderCatalog,
  type ProviderConfigBody,
  type ProviderTestResult,
  providerFaviconUrl,
  providersApi,
  type StoredProviderConfig,
} from "@/features/settings/api/providersApi";
import { SettingsPage } from "@/features/settings/components/ui/SettingsPage";
import { SettingsRow } from "@/features/settings/components/ui/SettingsRow";
import { SettingsSection } from "@/features/settings/components/ui/SettingsSection";
import { useProviderCatalog } from "@/features/settings/hooks/useProviderCatalog";
import { useProviderConfigs } from "@/features/settings/hooks/useProviderConfigs";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";
import {
  type CustomPreset,
  type CustomPresetKey,
  customPresetsFromCatalog,
} from "@/features/setup-wizard/utils/providerCards";
import { useConfirmation } from "@/hooks/useConfirmation";
import { toast } from "@/lib/toast";

interface ProviderRow {
  key: CredentialProvider;
  label: string;
  description: string;
  faviconDomain: string;
  needsBaseUrl: boolean;
  /** Tavily is a tool key — no model applies. */
  showModelField: boolean;
  /** Whether the backend can live-probe this credential (it cannot for Tavily). */
  connectionTestable: boolean;
}

/** A row's UI copy plus the endpoint defaults the catalog serves for it. */
interface CatalogProviderRow extends ProviderRow {
  defaultBaseUrl: string;
  defaultModel: string;
}

// UI copy only — endpoint defaults and display order come from GET /setup/catalog.
const PROVIDER_ROWS: ProviderRow[] = [
  {
    key: "openrouter",
    label: "OpenRouter",
    description: "One key for every major model. Easiest way to start.",
    faviconDomain: "openrouter.ai",
    needsBaseUrl: false,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "gemini",
    label: "Google Gemini",
    description: "Google's models, with a generous free tier.",
    faviconDomain: "ai.google.dev",
    needsBaseUrl: false,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "openai",
    label: "OpenAI",
    description:
      "GPT models directly from OpenAI. Also powers voice-note transcription.",
    faviconDomain: "openai.com",
    needsBaseUrl: false,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "ollama",
    label: "Ollama",
    description: "Run models locally — no API key needed.",
    faviconDomain: "ollama.com",
    needsBaseUrl: true,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "custom",
    label: "Custom Gateway",
    description:
      "Any OpenAI-compatible endpoint — OpenCode Zen, Nous Research, or your own.",
    faviconDomain: "opencode.ai",
    needsBaseUrl: true,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "tavily",
    label: "Tavily",
    description: "Web search results grounded in live sources.",
    faviconDomain: "tavily.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  // Tool / integration keys below mirror the tavily card shape: a single
  // credential, no endpoint or model, and no live probe (the test endpoint
  // only knows LLM wires).
  {
    key: "composio",
    label: "Composio",
    description:
      "Integration platform for Gmail, Calendar, Slack, and 200+ tools.",
    faviconDomain: "composio.dev",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "e2b",
    label: "E2B Sandbox",
    description: "Code execution sandbox for the agent's bash/code tools.",
    faviconDomain: "e2b.dev",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "resend",
    label: "Resend Email",
    description: "Outbound email for notifications and reminders.",
    faviconDomain: "resend.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "cloudinary",
    label: "Cloudinary",
    description:
      "Image upload and storage. Also needs CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_SECRET in .env — the key alone is not enough.",
    faviconDomain: "cloudinary.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "google_oauth",
    label: "Google OAuth",
    description:
      "Google account integration (Gmail, Calendar). Also needs GOOGLE_CLIENT_ID in .env — the secret alone cannot connect anything.",
    faviconDomain: "accounts.google.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "firecrawl",
    label: "Firecrawl",
    description: "Advanced web scraping and crawling.",
    faviconDomain: "firecrawl.dev",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
];

type CustomPresetId = CustomPresetKey | "manual";

function resolveProviderRow(
  key: CredentialProvider,
  catalog: ProviderCatalog,
): CatalogProviderRow {
  const row = PROVIDER_ROWS.find((r) => r.key === key);
  if (!row) throw new Error(`No settings copy for provider "${key}"`);
  const meta = catalog.providers[key];
  return {
    ...row,
    defaultBaseUrl: meta.base_url,
    defaultModel: meta.default_model,
  };
}

function StatusBadge({ configured }: { configured: boolean }) {
  if (configured) {
    return (
      <span className="flex items-center gap-1 rounded-full bg-emerald-400/10 px-2 py-0.5 text-xs font-medium text-emerald-400">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        Connected
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1 rounded-full bg-zinc-700/50 px-2 py-0.5 text-xs font-medium text-zinc-400">
      <span className="h-1.5 w-1.5 rounded-full bg-zinc-500" />
      Not configured
    </span>
  );
}

function ProviderFavicon({
  domain,
  size = 36,
}: {
  domain: string;
  size?: number;
}) {
  return (
    <Image
      src={providerFaviconUrl(domain)}
      alt=""
      width={size}
      height={size}
      className="rounded-xl object-contain"
      unoptimized
    />
  );
}

interface ConfigureProviderModalProps {
  row: CatalogProviderRow | null;
  /** Gateway chips offered when configuring the custom lane. */
  presets: readonly CustomPreset[];
  /** Masked stored config for this row, when the listing has loaded. */
  stored?: StoredProviderConfig;
  isConfigured: boolean;
  onSaved: () => void;
  onClose: () => void;
}

function ConfigureProviderModal({
  row,
  presets,
  stored,
  isConfigured,
  onSaved,
  onClose,
}: ConfigureProviderModalProps) {
  const { confirm, confirmationProps } = useConfirmation();
  const [apiKey, setApiKey] = useState("");
  const [isKeyVisible, setIsKeyVisible] = useState(false);
  const [baseUrl, setBaseUrl] = useState("");
  const [model, setModel] = useState("");
  const [preset, setPreset] = useState<CustomPresetId>("manual");
  const [isSaving, setIsSaving] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<ProviderTestResult | null>(null);

  const isOpen = row != null;

  // Upsert replaces the whole config, so seed from what is stored or a save wipes it.
  // The catalog model stays a placeholder: storing it would pin it past a default change.
  useEffect(() => {
    if (!row) return;
    setApiKey("");
    setBaseUrl(stored?.base_url || row.defaultBaseUrl);
    setModel(row.showModelField ? stored?.model || "" : "");
    setPreset(
      presets.find((p) => p.base_url === stored?.base_url)?.key ?? "manual",
    );
    setTestResult(null);
    setIsSaving(false);
    setIsTesting(false);
  }, [row, stored, presets]);

  if (!row) return null;

  // A stored key can never be read back (only its last four chars are
  // listed). Leaving the field empty keeps the stored key: the backend merges
  // a partial save instead of erasing it.
  const hasStoredKey = Boolean(stored?.api_key_hint);

  const selectPreset = (id: CustomPresetId) => {
    setPreset(id);
    setTestResult(null);
    if (id === "manual") return;
    const match = presets.find((p) => p.key === id);
    if (!match) return;
    setBaseUrl(match.base_url);
    setModel(match.default_model);
  };

  const presetChips: ReadonlyArray<{ id: CustomPresetId; label: string }> = [
    ...presets.map((p) => ({ id: p.key, label: p.label })),
    { id: "manual", label: "Manual" },
  ];

  const buildBody = (): ProviderConfigBody => {
    const body: ProviderConfigBody = {};
    if (apiKey.trim()) body.api_key = apiKey.trim();
    if (preset !== "manual") body.preset = preset;
    if (baseUrl.trim()) body.base_url = baseUrl.trim();
    if (row.showModelField && model.trim()) body.model = model.trim();
    return body;
  };

  const handleSave = async () => {
    setIsSaving(true);
    try {
      await providersApi.upsertProvider(row.key, buildBody());
      toast.success(`${row.label} connected`);
      onSaved();
    } catch (err: unknown) {
      const detail = extractProviderError(err);
      const hint = detail ? getProviderErrorHint(detail, row.key) : null;
      const message = hint
        ? `${detail} — ${hint}`
        : (detail ?? `Failed to save ${row.label}`);
      toast.error(message);
    } finally {
      setIsSaving(false);
    }
  };

  const handleRemove = async () => {
    const confirmed = await confirm({
      title: `Remove ${row.label}?`,
      message:
        "GAIA will stop using this key. If the same credential is also in your server config, that one still applies.",
      confirmText: "Remove",
      variant: "destructive",
    });
    if (!confirmed) return;
    try {
      await providersApi.deleteProvider(row.key);
      toast.success(`${row.label} removed`);
      onSaved();
    } catch {
      toast.error(`Failed to remove ${row.label}`);
    }
  };

  const handleTest = async () => {
    setIsTesting(true);
    setTestResult(null);
    try {
      const result = await providersApi.testProvider(row.key, buildBody());
      setTestResult(result);
    } catch (err: unknown) {
      const detail =
        extractProviderError(err) ?? "Could not reach GAIA to run the test.";
      setTestResult({
        ok: false,
        detail,
        models: [],
      });
    } finally {
      setIsTesting(false);
    }
  };

  const showPresetChips = row.key === "custom";

  return (
    <>
      <Modal isOpen={isOpen} onClose={onClose} size="md">
        <ModalContent>
          <ModalHeader className="flex-row items-center gap-3">
            <ProviderFavicon domain={row.faviconDomain} />
            Configure {row.label}
          </ModalHeader>
          <ModalBody className="gap-4">
            <Input
              autoFocus
              type={isKeyVisible ? "text" : "password"}
              label="API key"
              placeholder={
                hasStoredKey
                  ? `Stored (${stored?.api_key_hint}) — paste to replace`
                  : `Paste your ${row.label} key`
              }
              description={
                hasStoredKey
                  ? "Saved — leave empty to keep it, or paste to replace."
                  : undefined
              }
              value={apiKey}
              onValueChange={(value) => {
                setApiKey(value);
                setTestResult(null);
              }}
              endContent={
                <Button
                  isIconOnly
                  size="sm"
                  variant="light"
                  radius="full"
                  aria-label={isKeyVisible ? "Hide API key" : "Show API key"}
                  onPress={() => setIsKeyVisible((visible) => !visible)}
                  className="text-zinc-500"
                >
                  {isKeyVisible ? (
                    <ViewOffSlashIcon size={16} />
                  ) : (
                    <ViewIcon size={16} />
                  )}
                </Button>
              }
            />
            {PROVIDER_KEY_URLS[row.key] && (
              <Link
                href={PROVIDER_KEY_URLS[row.key] as string}
                isExternal
                size="sm"
                className="inline-flex items-center gap-1 text-xs text-zinc-500"
              >
                Get your key
                <SquareArrowUpRight02Icon size={12} />
              </Link>
            )}
            {(row.needsBaseUrl || showPresetChips) && (
              <>
                {showPresetChips && (
                  <div className="space-y-2">
                    <p className="text-xs font-medium tracking-wider text-zinc-500 uppercase">
                      Preset gateway
                    </p>
                    <div className="flex gap-2">
                      {presetChips.map((chip) => (
                        <Button
                          key={chip.id}
                          size="sm"
                          variant={preset === chip.id ? "flat" : "light"}
                          color={preset === chip.id ? "primary" : "default"}
                          onPress={() => selectPreset(chip.id)}
                        >
                          {chip.label}
                        </Button>
                      ))}
                    </div>
                  </div>
                )}
                <Input
                  label="Base URL"
                  placeholder={
                    row.defaultBaseUrl || "https://your-gateway.example.com/v1"
                  }
                  value={baseUrl}
                  onValueChange={(value) => {
                    setBaseUrl(value);
                    setTestResult(null);
                  }}
                />
              </>
            )}
            {row.showModelField && (
              <Input
                label="Model"
                placeholder={row.defaultModel || "Default"}
                description="Leave empty to use the endpoint default."
                value={model}
                onValueChange={(value) => {
                  setModel(value);
                  setTestResult(null);
                }}
              />
            )}
            {testResult && (
              <div
                className={`rounded-xl p-3 text-xs ${
                  testResult.ok
                    ? "bg-emerald-400/10 text-emerald-400"
                    : "bg-red-400/10 text-red-400"
                }`}
              >
                <p>{testResult.detail}</p>
                {!testResult.ok &&
                  (() => {
                    const hint = getProviderErrorHint(
                      testResult.detail,
                      row.key,
                    );
                    return hint ? (
                      <p className="mt-1 text-xs leading-relaxed text-zinc-500">
                        {hint}
                      </p>
                    ) : null;
                  })()}
                {testResult.ok && testResult.models.length > 0 && (
                  <p className="mt-1 text-zinc-400">
                    {testResult.models.length} models available
                  </p>
                )}
              </div>
            )}
            {row.connectionTestable && testResult?.ok !== true && (
              <p className="text-xs text-zinc-500">
                Run Test first — Save unlocks after a passing test.
              </p>
            )}
          </ModalBody>
          <ModalFooter>
            {isConfigured && (
              <Button
                color="danger"
                variant="light"
                size="sm"
                onPress={() => {
                  void handleRemove();
                }}
              >
                Remove
              </Button>
            )}
            <Button variant="flat" size="sm" onPress={onClose}>
              Cancel
            </Button>
            {row.connectionTestable && (
              <Button
                variant="flat"
                color="default"
                size="sm"
                isLoading={isTesting}
                isDisabled={isSaving}
                onPress={() => {
                  void handleTest();
                }}
              >
                Test
              </Button>
            )}
            <Button
              color="primary"
              size="sm"
              isLoading={isSaving}
              isDisabled={
                isTesting || (row.connectionTestable && testResult?.ok !== true)
              }
              onPress={() => {
                void handleSave();
              }}
            >
              Save
            </Button>
          </ModalFooter>
        </ModalContent>
      </Modal>
      <ConfirmationDialog {...confirmationProps} />
    </>
  );
}

export function ProvidersSettings() {
  const { data: status, refetch: refetchStatus } = useSetupStatus();
  const {
    data: storedConfigs,
    isLoading: isLoadingConfigs,
    refetch: refetchConfigs,
  } = useProviderConfigs();
  const { data: catalog, isError: isCatalogError } = useProviderCatalog();
  const [editingKey, setEditingKey] = useState<CredentialProvider | null>(null);

  // The catalog serves every credential-store provider in display order.
  // Memoized so the open modal's seeding effect doesn't re-run per render.
  const { displayRows, presets } = useMemo(
    () =>
      catalog
        ? {
            displayRows: (
              Object.keys(catalog.providers) as CredentialProvider[]
            ).map((key) => resolveProviderRow(key, catalog)),
            presets: customPresetsFromCatalog(catalog),
          }
        : { displayRows: [], presets: [] },
    [catalog],
  );

  const editingRow = displayRows.find((r) => r.key === editingKey) ?? null;

  return (
    <SettingsPage>
      <SettingsSection description="Connect the AI providers, tools, and integrations GAIA runs on.">
        {!catalog && !isCatalogError && <Spinner size="sm" />}
        {isCatalogError && (
          <p className="text-sm text-zinc-400">
            Couldn&apos;t load the provider list. Reload the page to try again.
          </p>
        )}
        {displayRows.map((row) => {
          const configured = status?.providers?.[row.key]?.configured === true;

          return (
            <SettingsRow
              key={row.key}
              label={row.label}
              description={row.description}
              icon={<ProviderFavicon domain={row.faviconDomain} />}
            >
              <div className="flex items-center gap-3">
                <StatusBadge configured={configured} />
                <Button
                  variant="flat"
                  color="default"
                  size="sm"
                  className="text-xs"
                  isDisabled={isLoadingConfigs}
                  onPress={() => setEditingKey(row.key)}
                >
                  Configure
                </Button>
              </div>
            </SettingsRow>
          );
        })}
      </SettingsSection>

      <ConfigureProviderModal
        row={editingRow}
        presets={presets}
        stored={editingKey != null ? storedConfigs?.[editingKey] : undefined}
        isConfigured={
          editingKey != null &&
          status?.providers?.[editingKey]?.configured === true
        }
        onSaved={() => {
          void refetchStatus();
          void refetchConfigs();
          setEditingKey(null);
        }}
        onClose={() => setEditingKey(null)}
      />
    </SettingsPage>
  );
}
