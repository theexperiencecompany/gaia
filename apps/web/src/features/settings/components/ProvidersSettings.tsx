"use client";

import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import {
  Modal,
  ModalBody,
  ModalContent,
  ModalFooter,
  ModalHeader,
} from "@heroui/modal";
import { SquareArrowUpRight02Icon, ViewIcon, ViewOffSlashIcon } from "@icons";
import { useQuery } from "@tanstack/react-query";
import Image from "next/image";
import { useEffect, useState } from "react";
import { ConfirmationDialog } from "@/components/shared/ConfirmationDialog";
import {
  type CredentialProvider,
  CUSTOM_PRESETS,
  type CustomPreset,
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
import { useProviderConfigs } from "@/features/settings/hooks/useProviderConfigs";
import { useSetupStatus } from "@/features/settings/hooks/useSetupStatus";
import { useConfirmation } from "@/hooks/useConfirmation";
import { toast } from "@/lib/toast";

interface ProviderRow {
  key: CredentialProvider;
  label: string;
  description: string;
  faviconDomain: string;
  needsBaseUrl: boolean;
  defaultBaseUrl?: string;
  defaultModel?: string;
  /** Tavily is a tool key — no model applies. */
  showModelField: boolean;
  /** Whether the backend can live-probe this credential (it cannot for Tavily). */
  connectionTestable: boolean;
}

// Mirrors PRESETS in app/constants/providers.py.
const PROVIDER_ROWS: ProviderRow[] = [
  {
    key: "openrouter",
    label: "OpenRouter",
    description: "Route GAIA's LLM calls through OpenRouter.",
    faviconDomain: "openrouter.ai",
    needsBaseUrl: false,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "gemini",
    label: "Google Gemini",
    description: "Use Google's Gemini models with an API key.",
    faviconDomain: "ai.google.dev",
    needsBaseUrl: false,
    showModelField: true,
    connectionTestable: true,
  },
  {
    key: "ollama",
    label: "Ollama",
    description: "Run local open-source models through Ollama.",
    faviconDomain: "ollama.com",
    needsBaseUrl: true,
    defaultBaseUrl: "http://host.docker.internal:11434",
    defaultModel: "llama3.2",
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
    description: "API key for the Tavily web search tools.",
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
    key: "openai",
    label: "OpenAI",
    description: "Used for voice-note transcription (Whisper).",
    faviconDomain: "openai.com",
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
    description: "Image upload and storage for chat media.",
    faviconDomain: "cloudinary.com",
    needsBaseUrl: false,
    showModelField: false,
    connectionTestable: false,
  },
  {
    key: "google_oauth",
    label: "Google OAuth",
    description: "Google account integration (Gmail, Calendar).",
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

// Preset gateways for the custom lane come from the shared catalog in
// providersApi (CUSTOM_PRESETS) — paste an API key and go.
type CustomPresetId = CustomPreset["key"] | "manual";

const PRESET_CHIPS: ReadonlyArray<{ id: CustomPresetId; label: string }> = [
  ...CUSTOM_PRESETS.map((p) => ({ id: p.key, label: p.label })),
  { id: "manual", label: "Manual" },
];

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
  row: ProviderRow | null;
  /** Masked stored config for this row, when the listing has loaded. */
  stored?: StoredProviderConfig;
  isConfigured: boolean;
  onSaved: () => void;
  onClose: () => void;
}

function useProviderCatalog() {
  return useQuery<ProviderCatalog>({
    queryKey: ["setup", "catalog"],
    queryFn: () => providersApi.fetchCatalog(),
    staleTime: 60_000,
    retry: false,
  });
}

function ConfigureProviderModal({
  row,
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

  // Seed from the STORED config (masked listing), falling back to row
  // defaults. The upsert endpoint replaces a provider's whole config, so
  // saving must carry the resolved base_url/model or they would be wiped.
  useEffect(() => {
    if (!row) return;
    setApiKey("");
    setBaseUrl(stored?.base_url || row.defaultBaseUrl || "");
    setModel(row.showModelField ? stored?.model || row.defaultModel || "" : "");
    setPreset(
      CUSTOM_PRESETS.find((p) => p.baseUrl === stored?.base_url)?.key ??
        "manual",
    );
    setTestResult(null);
    setIsSaving(false);
    setIsTesting(false);
  }, [row, stored]);

  if (!row) return null;

  // A stored key can never be read back (only its last four chars are listed)
  // and an upsert that omits api_key deletes it — so updating anything about a
  // key-backed provider requires pasting the key again.
  const hasStoredKey = Boolean(stored?.api_key_hint);
  const needsKeyReentry = hasStoredKey && apiKey.trim().length === 0;

  const selectPreset = (id: CustomPresetId) => {
    setPreset(id);
    setTestResult(null);
    if (id === "manual") return;
    const match = CUSTOM_PRESETS.find((p) => p.key === id);
    if (!match) return;
    setBaseUrl(match.baseUrl);
    setModel(match.defaultModel);
  };

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
        "GAIA will stop using this provider and fall back to any environment variables configured for it.",
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
                  ? "Saved keys can't be read back — paste yours again to keep or replace it."
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
              <a
                href={PROVIDER_KEY_URLS[row.key]}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs text-zinc-500 hover:text-zinc-300"
              >
                Get your key
                <SquareArrowUpRight02Icon size={12} />
              </a>
            )}
            {(row.needsBaseUrl || showPresetChips) && (
              <>
                {showPresetChips && (
                  <div className="space-y-2">
                    <p className="text-xs font-medium tracking-wider text-zinc-500 uppercase">
                      Preset gateway
                    </p>
                    <div className="flex gap-2">
                      {PRESET_CHIPS.map((chip) => (
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
                    row.defaultBaseUrl ?? "https://your-gateway.example.com/v1"
                  }
                  value={baseUrl}
                  onValueChange={setBaseUrl}
                />
              </>
            )}
            {row.showModelField && (
              <Input
                label="Model"
                placeholder="Default"
                description="Leave empty to use the endpoint default."
                value={model}
                onValueChange={setModel}
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
              isDisabled={isTesting || needsKeyReentry}
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

function getProviderErrorHint(
  detail: string,
  providerKey?: string,
): string | null {
  const lower = detail.toLowerCase();
  if (lower.includes("private") || lower.includes("unreachable")) return null;
  if (
    lower.includes("401") ||
    lower.includes("invalid") ||
    lower.includes("unauthorized")
  ) {
    const url = providerKey
      ? (PROVIDER_KEY_URLS as Record<string, string>)[providerKey]
      : undefined;
    if (url) {
      return `Check your API key at ${url} — it may be expired or missing permissions.`;
    }
    return "Check your API key — it may be expired or missing permissions.";
  }
  if (lower.includes("429") || lower.includes("rate")) {
    return "Rate limited — wait a minute and try again, or check your plan limits.";
  }
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return "Provider didn't respond — check your network or try again.";
  }
  return null;
}

/** Pull a human-readable message out of an axios/backend error. */
function extractProviderError(err: unknown): string | undefined {
  if (typeof err === "object" && err !== null) {
    const data = (err as { response?: { data?: unknown } }).response?.data;
    if (typeof data === "object" && data !== null) {
      const record = data as Record<string, unknown>;
      if (typeof record.detail === "string") return record.detail;
      if (
        typeof record.detail === "object" &&
        record.detail !== null &&
        typeof (record.detail as Record<string, unknown>).message === "string"
      ) {
        return (record.detail as Record<string, unknown>).message as string;
      }
      if (typeof record.message === "string") return record.message;
    }
    if (err instanceof Error && err.message) return err.message;
  }
  return undefined;
}

export function ProvidersSettings() {
  const { data: status, refetch: refetchStatus } = useSetupStatus();
  const {
    data: storedConfigs,
    isLoading: isLoadingConfigs,
    refetch: refetchConfigs,
  } = useProviderConfigs();
  const { data: catalog } = useProviderCatalog();
  const [editingKey, setEditingKey] = useState<CredentialProvider | null>(null);

  // Prefer the live catalog from GET /setup/catalog (backend is now source of
  // truth); fall back to the hardcoded PROVIDER_ROWS so older builds or a
  // failed fetch still render every row.
  const displayRows: ProviderRow[] = catalog
    ? (
        Object.entries(catalog.providers) as [
          CredentialProvider,
          ProviderCatalog["providers"][CredentialProvider],
        ][]
      ).map(([key, meta]) => {
        const fallback = PROVIDER_ROWS.find((r) => r.key === key);
        return {
          key,
          label: meta.label || fallback?.label || key,
          description: fallback?.description || meta.description || "",
          faviconDomain: meta.favicon_domain || fallback?.faviconDomain || "",
          needsBaseUrl: meta.needs_base_url ?? fallback?.needsBaseUrl ?? false,
          defaultBaseUrl:
            meta.base_url || meta.default_base_url || fallback?.defaultBaseUrl,
          defaultModel: meta.default_model || fallback?.defaultModel,
          showModelField: fallback?.showModelField ?? true,
          connectionTestable: fallback?.connectionTestable ?? false,
        };
      })
    : PROVIDER_ROWS;

  const editingRow = displayRows.find((r) => r.key === editingKey) ?? null;

  return (
    <SettingsPage>
      <SettingsSection description="Connect the AI providers, tools, and integrations GAIA runs on.">
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
