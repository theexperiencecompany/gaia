import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { Image } from "expo-image";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import {
  ActivityIndicator,
  Alert,
  Pressable,
  TextInput,
  View,
} from "react-native";
import {
  Alert01Icon,
  AppIcon,
  CheckmarkCircle02Icon,
  Delete02Icon,
  Edit02Icon,
  LinkSquare02Icon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type { TestConnectionResponse } from "../api/integrations-api";
import {
  connectIntegration,
  deleteCustomIntegration,
  disconnectIntegration,
  testIntegrationConnection,
} from "../api/integrations-api";
import type { Integration } from "../types";

// ─── Types ───────────────────────────────────────────────────────────────────
export interface IntegrationDetailSheetRef {
  open: (integration: Integration) => void;
  close: () => void;
}

interface IntegrationDetailSheetProps {
  onConnect?: (
    integrationId: string,
    authType?: string,
    token?: string,
  ) => void;
  onDisconnect?: (integrationId: string) => void;
  onDelete?: (integrationId: string) => void;
  onEdit?: (integration: Integration) => void;
  onRefresh?: () => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

const INTEGRATION_LOGOS: Record<string, string> = {
  googlecalendar:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a5/Google_Calendar_icon_%282020%29.svg/512px-Google_Calendar_icon_%282020%29.svg.png",
  googledocs:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/0/01/Google_Docs_logo_%282020%29.svg/512px-Google_Docs_logo_%282020%29.svg.png",
  gmail:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7e/Gmail_icon_%282020%29.svg/512px-Gmail_icon_%282020%29.svg.png",
  notion:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/512px-Notion-logo.svg.png",
  twitter:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6f/Logo_of_Twitter.svg/512px-Logo_of_Twitter.svg.png",
  googlesheets:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a0/Google_Sheets_logo_%282020%29.svg/512px-Google_Sheets_logo_%282014-2020%29.svg.png",
  linkedin:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/ca/LinkedIn_logo_initials.png/512px-LinkedIn_logo_initials.png",
  github:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c2/GitHub_Invertocat_Logo.svg/512px-GitHub_Invertocat_Logo.svg.png",
  reddit:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b4/Reddit_logo.svg/512px-Reddit_logo.svg.png",
  airtable:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4b/Airtable_Logo.svg/512px-Airtable_Logo.svg.png",
  linear:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/59/Linear_logo.svg/512px-Linear_logo.svg.png",
  slack:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d5/Slack_icon_2019.svg/512px-Slack_icon_2019.svg.png",
  hubspot:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3f/HubSpot_Logo.svg/512px-HubSpot_Logo.svg.png",
  googletasks:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/5/5b/Google_Tasks_2021.svg/512px-Google_Tasks_2021.svg.png",
  todoist:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/6/6d/Todoist_logo.svg/512px-Todoist_logo.svg.png",
  googlemeet:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9b/Google_Meet_icon_%282020%29.svg/512px-Google_Meet_icon_%282020%29.svg.png",
  google_maps:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/aa/Google_Maps_icon_%282020%29.svg/512px-Google_Maps_icon_%282020%29.svg.png",
  asana:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3b/Asana_logo.svg/512px-Asana_logo.svg.png",
  trello:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/7a/Trello-logo-blue.svg/512px-Trello-logo-blue.svg.png",
  instagram:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e7/Instagram_logo_2016.svg/512px-Instagram_logo_2016.svg.png",
  clickup:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/7/75/ClickUp_Logo.svg/512px-ClickUp_Logo.svg.png",
};

function getLogoUri(integration: Integration): string {
  if (integration.iconUrl) return integration.iconUrl;
  return (
    INTEGRATION_LOGOS[integration.id] ??
    "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ac/No_image_available.svg/512px-No_image_available.svg.png"
  );
}

const CATEGORY_LABELS: Record<string, string> = {
  productivity: "Productivity",
  developer: "Developer",
  communication: "Communication",
  analytics: "Analytics",
  finance: "Finance",
  "ai-ml": "AI & ML",
  education: "Education",
  personal: "Personal",
  capabilities: "Capabilities",
  other: "Other",
};

function getCategoryLabel(cat: string): string {
  return (
    CATEGORY_LABELS[cat] ??
    cat
      .split("_")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ")
  );
}

function getAuthTypeLabel(authType: string): string {
  if (authType === "oauth") return "OAuth";
  if (authType === "bearer") return "Bearer Token";
  if (authType === "none") return "No Auth";
  return authType;
}

function getManagedByLabel(managedBy: string): string {
  if (managedBy === "composio") return "Composio";
  if (managedBy === "mcp") return "MCP";
  if (managedBy === "internal") return "Internal";
  return "Self";
}

// ─── Sub-components ───────────────────────────────────────────────────────────

interface BadgeProps {
  label: string;
  color: string;
  bg: string;
}

function Badge({ label, color, bg }: BadgeProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();
  return (
    <View
      style={{
        backgroundColor: bg,
        borderRadius: moderateScale(20, 0.5),
        paddingHorizontal: spacing.sm + 2,
        paddingVertical: 4,
      }}
    >
      <Text style={{ fontSize: fontSize.xs, color, fontWeight: "500" }}>
        {label}
      </Text>
    </View>
  );
}

interface StatusPillProps {
  status: Integration["status"];
}

function StatusPill({ status }: StatusPillProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();

  const config: Record<
    string,
    { label: string; color: string; bg: string; dot: string }
  > = {
    connected: {
      label: "Connected",
      color: "#34c759",
      bg: "rgba(52,199,89,0.12)",
      dot: "#34c759",
    },
    not_connected: {
      label: "Not Connected",
      color: "#71717a",
      bg: "rgba(113,113,122,0.12)",
      dot: "#71717a",
    },
    created: {
      label: "Pending",
      color: "#f59e0b",
      bg: "rgba(245,158,11,0.12)",
      dot: "#f59e0b",
    },
    error: {
      label: "Error",
      color: "#ef4444",
      bg: "rgba(239,68,68,0.12)",
      dot: "#ef4444",
    },
  };

  const cfg = config[status] ?? config.not_connected;

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        backgroundColor: cfg.bg,
        borderRadius: moderateScale(20, 0.5),
        paddingHorizontal: spacing.md,
        paddingVertical: 6,
        alignSelf: "flex-start",
      }}
    >
      <View
        style={{
          width: 7,
          height: 7,
          borderRadius: 4,
          backgroundColor: cfg.dot,
        }}
      />
      <Text
        style={{ fontSize: fontSize.sm, color: cfg.color, fontWeight: "600" }}
      >
        {cfg.label}
      </Text>
    </View>
  );
}

interface ToolItemProps {
  name: string;
  description?: string;
}

function ToolItem({ name, description }: ToolItemProps) {
  const { fontSize, spacing } = useResponsive();
  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "flex-start",
        gap: spacing.sm,
        paddingVertical: spacing.xs,
      }}
    >
      <View
        style={{
          width: 4,
          height: 4,
          borderRadius: 2,
          backgroundColor: "#00bbff",
          marginTop: 7,
          flexShrink: 0,
        }}
      />
      <View style={{ flex: 1 }}>
        <Text
          style={{ fontSize: fontSize.sm, color: "#e4e4e7", fontWeight: "500" }}
        >
          {name}
        </Text>
        {description ? (
          <Text
            style={{ fontSize: fontSize.xs, color: "#71717a", marginTop: 2 }}
          >
            {description}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

interface TestResultBannerProps {
  isLoading: boolean;
  result: TestConnectionResponse | null;
  error: string | null;
}

function TestResultBanner({ isLoading, result, error }: TestResultBannerProps) {
  const { fontSize, spacing, moderateScale } = useResponsive();

  if (isLoading) {
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          backgroundColor: "rgba(255,255,255,0.05)",
          borderRadius: moderateScale(12, 0.5),
          padding: spacing.md,
        }}
      >
        <ActivityIndicator size="small" color="#00bbff" />
        <Text style={{ fontSize: fontSize.sm, color: "#8e8e93" }}>
          Testing connection...
        </Text>
      </View>
    );
  }

  if (error) {
    return (
      <View
        style={{
          backgroundColor: "rgba(239,68,68,0.08)",
          borderRadius: moderateScale(12, 0.5),
          padding: spacing.md,
          gap: spacing.xs,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          <AppIcon icon={Alert01Icon} size={15} color="#ef4444" />
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#ef4444",
            }}
          >
            Test Failed
          </Text>
        </View>
        <Text style={{ fontSize: fontSize.xs, color: "#f87171" }}>{error}</Text>
      </View>
    );
  }

  if (!result) return null;

  if (result.status === "connected") {
    const count = result.tools_count ?? 0;
    return (
      <View
        style={{
          backgroundColor: "rgba(52,199,89,0.08)",
          borderRadius: moderateScale(12, 0.5),
          padding: spacing.md,
          gap: spacing.xs,
        }}
      >
        <View
          style={{
            flexDirection: "row",
            alignItems: "center",
            gap: spacing.sm,
          }}
        >
          <AppIcon icon={CheckmarkCircle02Icon} size={15} color="#34c759" />
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#34c759",
            }}
          >
            Connection OK
          </Text>
        </View>
        <Text style={{ fontSize: fontSize.xs, color: "#71b88a" }}>
          {count === 0
            ? "No tools discovered"
            : `${count} tool${count !== 1 ? "s" : ""} available`}
        </Text>
      </View>
    );
  }

  return (
    <View
      style={{
        backgroundColor: "rgba(239,68,68,0.08)",
        borderRadius: moderateScale(12, 0.5),
        padding: spacing.md,
        gap: spacing.xs,
      }}
    >
      <View
        style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm }}
      >
        <AppIcon icon={Alert01Icon} size={15} color="#ef4444" />
        <Text
          style={{ fontSize: fontSize.sm, fontWeight: "600", color: "#ef4444" }}
        >
          Connection Failed
        </Text>
      </View>
      {result.error ? (
        <Text style={{ fontSize: fontSize.xs, color: "#f87171" }}>
          {result.error}
        </Text>
      ) : null}
    </View>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export const IntegrationDetailSheet = forwardRef<
  IntegrationDetailSheetRef,
  IntegrationDetailSheetProps
>(({ onConnect, onDisconnect, onDelete, onEdit, onRefresh }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [integration, setIntegration] = useState<Integration | null>(null);

  const [showTokenInput, setShowTokenInput] = useState(false);
  const [bearerToken, setBearerToken] = useState("");
  const [descExpanded, setDescExpanded] = useState(false);
  const [toolsExpanded, setToolsExpanded] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResponse | null>(
    null,
  );
  const [testError, setTestError] = useState<string | null>(null);

  const { spacing, fontSize, moderateScale } = useResponsive();

  const snapPoints = useMemo(() => ["60%", "90%"], []);

  const reset = useCallback(() => {
    setShowTokenInput(false);
    setBearerToken("");
    setDescExpanded(false);
    setToolsExpanded(false);
    setIsConnecting(false);
    setIsDisconnecting(false);
    setIsDeleting(false);
    setIsTesting(false);
    setTestResult(null);
    setTestError(null);
  }, []);

  useImperativeHandle(ref, () => ({
    open: (i: Integration) => {
      setIntegration(i);
      reset();
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const handleConnect = useCallback(async () => {
    if (!integration) return;
    const authType = integration.authType ?? "oauth";
    if (authType === "bearer" && !showTokenInput) {
      setShowTokenInput(true);
      return;
    }

    setIsConnecting(true);
    try {
      const result = await connectIntegration(integration.id);
      if (result.success) {
        onConnect?.(integration.id);
        onRefresh?.();
        setIsOpen(false);
      } else if (!result.cancelled) {
        Alert.alert("Error", result.error ?? "Failed to connect integration");
      }
    } finally {
      setIsConnecting(false);
    }
  }, [integration, showTokenInput, onConnect, onRefresh]);

  const handleDisconnect = useCallback(() => {
    if (!integration) return;
    Alert.alert(
      "Disconnect Integration",
      `Disconnect ${integration.name}? This will remove your connection.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Disconnect",
          style: "destructive",
          onPress: async () => {
            setIsDisconnecting(true);
            try {
              const success = await disconnectIntegration(integration.id);
              if (success) {
                onDisconnect?.(integration.id);
                onRefresh?.();
                setIsOpen(false);
              } else {
                Alert.alert("Error", "Failed to disconnect integration");
              }
            } finally {
              setIsDisconnecting(false);
            }
          },
        },
      ],
    );
  }, [integration, onDisconnect, onRefresh]);

  const handleTestConnection = useCallback(async () => {
    if (!integration) return;
    setIsTesting(true);
    setTestResult(null);
    setTestError(null);
    try {
      const result = await testIntegrationConnection(integration.id);
      setTestResult(result);
    } catch (err) {
      setTestError(err instanceof Error ? err.message : "Test failed");
    } finally {
      setIsTesting(false);
    }
  }, [integration]);

  const handleDelete = useCallback(() => {
    if (!integration) return;
    Alert.alert(
      "Delete Integration",
      `Delete ${integration.name}? This cannot be undone.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            setIsDeleting(true);
            try {
              await deleteCustomIntegration(integration.id);
              onDelete?.(integration.id);
              onRefresh?.();
              setIsOpen(false);
            } catch {
              Alert.alert("Error", "Failed to delete integration");
            } finally {
              setIsDeleting(false);
            }
          },
        },
      ],
    );
  }, [integration, onDelete, onRefresh]);

  const handleEdit = useCallback(() => {
    if (!integration) return;
    onEdit?.(integration);
    setIsOpen(false);
  }, [integration, onEdit]);

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={snapPoints}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#0b0c0f" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          {integration ? (
            <BottomSheetScrollView
              contentContainerStyle={{
                padding: spacing.lg,
                gap: spacing.lg,
                paddingBottom: spacing.xl * 2,
              }}
            >
              {(() => {
                const isConnected = integration.status === "connected";
                const isError = integration.status === "error";
                const isCustom = integration.source === "custom";
                const authType = integration.authType ?? "oauth";
                const managedBy = integration.managedBy ?? "self";
                const tools = integration.tools ?? [];
                const TOOLS_INITIAL_COUNT = 5;
                const visibleTools = toolsExpanded
                  ? tools
                  : tools.slice(0, TOOLS_INITIAL_COUNT);
                const hasMoreTools = tools.length > TOOLS_INITIAL_COUNT;
                const descriptionIsLong = integration.description.length > 120;
                const displayedDescription =
                  descExpanded || !descriptionIsLong
                    ? integration.description
                    : `${integration.description.slice(0, 120)}...`;
                const logoUri = getLogoUri(integration);
                const firstLetter = (integration.name ?? "?")[0].toUpperCase();

                return (
                  <>
                    {/* ─── Header: Logo + Name ───────────────────────────── */}
                    <View style={{ alignItems: "center", gap: spacing.md }}>
                      <View
                        style={{
                          width: 80,
                          height: 80,
                          borderRadius: 40,
                          backgroundColor: "rgba(255,255,255,0.07)",
                          alignItems: "center",
                          justifyContent: "center",
                          overflow: "hidden",
                        }}
                      >
                        {logoUri ? (
                          <Image
                            source={{ uri: logoUri }}
                            style={{ width: 54, height: 54 }}
                            contentFit="contain"
                          />
                        ) : (
                          <Text
                            style={{
                              fontSize: fontSize["2xl"],
                              color: "#a1a1aa",
                            }}
                          >
                            {firstLetter}
                          </Text>
                        )}
                      </View>

                      <Text
                        style={{
                          fontSize: fontSize["2xl"],
                          fontWeight: "700",
                          color: "#f4f4f5",
                          textAlign: "center",
                        }}
                      >
                        {integration.name}
                      </Text>

                      <StatusPill status={integration.status} />

                      <View
                        style={{
                          flexDirection: "row",
                          flexWrap: "wrap",
                          gap: spacing.sm,
                          justifyContent: "center",
                        }}
                      >
                        <Badge
                          label={getCategoryLabel(integration.category)}
                          color="#a1a1aa"
                          bg="rgba(255,255,255,0.07)"
                        />
                        {authType !== "none" && (
                          <Badge
                            label={getAuthTypeLabel(authType)}
                            color="#00bbff"
                            bg="rgba(0,187,255,0.1)"
                          />
                        )}
                        {managedBy && managedBy !== "self" && (
                          <Badge
                            label={getManagedByLabel(managedBy)}
                            color="#c084fc"
                            bg="rgba(192,132,252,0.1)"
                          />
                        )}
                        {isCustom && (
                          <Badge
                            label="Custom"
                            color="#f59e0b"
                            bg="rgba(245,158,11,0.1)"
                          />
                        )}
                      </View>
                    </View>

                    {/* ─── Description ──────────────────────────────────── */}
                    {integration.description ? (
                      <View style={{ gap: spacing.xs }}>
                        <Text
                          style={{
                            fontSize: fontSize.sm,
                            color: "#a1a1aa",
                            lineHeight: 20,
                          }}
                        >
                          {displayedDescription}
                        </Text>
                        {descriptionIsLong && (
                          <Pressable
                            onPress={() => setDescExpanded((v) => !v)}
                            hitSlop={8}
                          >
                            <Text
                              style={{
                                fontSize: fontSize.xs,
                                color: "#00bbff",
                                fontWeight: "500",
                              }}
                            >
                              {descExpanded ? "Show less" : "Show more"}
                            </Text>
                          </Pressable>
                        )}
                      </View>
                    ) : null}

                    {/* ─── Bearer token input ────────────────────────────── */}
                    {showTokenInput && !isConnected && (
                      <View
                        style={{
                          gap: spacing.sm,
                          backgroundColor: "rgba(255,255,255,0.04)",
                          borderRadius: moderateScale(12, 0.5),
                          padding: spacing.md,
                        }}
                      >
                        <Text
                          style={{
                            fontSize: fontSize.sm,
                            color: "#a1a1aa",
                            fontWeight: "500",
                          }}
                        >
                          API Token
                        </Text>
                        <TextInput
                          value={bearerToken}
                          onChangeText={setBearerToken}
                          placeholder="Paste your bearer token..."
                          placeholderTextColor="#52525b"
                          secureTextEntry
                          autoFocus
                          style={{
                            borderWidth: 1,
                            borderColor: bearerToken
                              ? "rgba(0,187,255,0.4)"
                              : "#3f3f46",
                            borderRadius: moderateScale(10, 0.5),
                            padding: spacing.md,
                            color: "#fff",
                            fontSize: fontSize.sm,
                            backgroundColor: "#1c1c1e",
                          }}
                        />
                      </View>
                    )}

                    {/* ─── Update token option ───────────────────────────── */}
                    {isConnected &&
                      authType === "bearer" &&
                      !showTokenInput && (
                        <Pressable
                          onPress={() => setShowTokenInput(true)}
                          style={({ pressed }) => ({
                            flexDirection: "row",
                            alignItems: "center",
                            gap: spacing.sm,
                            padding: spacing.md,
                            borderRadius: moderateScale(12, 0.5),
                            backgroundColor: pressed
                              ? "rgba(255,255,255,0.06)"
                              : "rgba(255,255,255,0.04)",
                            borderWidth: 1,
                            borderColor: "rgba(255,255,255,0.08)",
                          })}
                        >
                          <AppIcon
                            icon={LinkSquare02Icon}
                            size={16}
                            color="#00bbff"
                          />
                          <Text
                            style={{
                              fontSize: fontSize.sm,
                              color: "#00bbff",
                              fontWeight: "500",
                            }}
                          >
                            Update API Token
                          </Text>
                        </Pressable>
                      )}

                    {/* ─── Primary connect/disconnect action ────────────── */}
                    <View style={{ gap: spacing.sm }}>
                      {isConnected || isError ? (
                        <Pressable
                          onPress={handleDisconnect}
                          disabled={isDisconnecting}
                          style={({ pressed }) => ({
                            padding: spacing.md,
                            borderRadius: moderateScale(14, 0.5),
                            backgroundColor: pressed
                              ? "rgba(239,68,68,0.15)"
                              : "rgba(239,68,68,0.1)",
                            borderWidth: 1,
                            borderColor: "rgba(239,68,68,0.3)",
                            alignItems: "center",
                            flexDirection: "row",
                            justifyContent: "center",
                            gap: spacing.sm,
                            opacity: isDisconnecting ? 0.6 : 1,
                          })}
                        >
                          {isDisconnecting ? (
                            <ActivityIndicator size="small" color="#ef4444" />
                          ) : null}
                          <Text
                            style={{
                              color: "#ef4444",
                              fontSize: fontSize.sm,
                              fontWeight: "600",
                            }}
                          >
                            {isDisconnecting
                              ? "Disconnecting..."
                              : "Disconnect"}
                          </Text>
                        </Pressable>
                      ) : (
                        <Pressable
                          onPress={handleConnect}
                          disabled={isConnecting}
                          style={({ pressed }) => ({
                            padding: spacing.md,
                            borderRadius: moderateScale(14, 0.5),
                            backgroundColor: pressed ? "#009dd4" : "#00bbff",
                            alignItems: "center",
                            flexDirection: "row",
                            justifyContent: "center",
                            gap: spacing.sm,
                            opacity: isConnecting ? 0.7 : 1,
                          })}
                        >
                          {isConnecting ? (
                            <ActivityIndicator size="small" color="#000" />
                          ) : null}
                          <Text
                            style={{
                              color: "#000",
                              fontSize: fontSize.sm,
                              fontWeight: "700",
                            }}
                          >
                            {isConnecting
                              ? "Connecting..."
                              : showTokenInput
                                ? "Save Token & Connect"
                                : "Connect"}
                          </Text>
                        </Pressable>
                      )}

                      {isConnected && (
                        <Pressable
                          onPress={handleTestConnection}
                          disabled={isTesting}
                          style={({ pressed }) => ({
                            padding: spacing.md,
                            borderRadius: moderateScale(14, 0.5),
                            backgroundColor: pressed
                              ? "rgba(255,255,255,0.07)"
                              : "rgba(255,255,255,0.04)",
                            borderWidth: 1,
                            borderColor: "rgba(255,255,255,0.1)",
                            alignItems: "center",
                            flexDirection: "row",
                            justifyContent: "center",
                            gap: spacing.sm,
                            opacity: isTesting ? 0.6 : 1,
                          })}
                        >
                          {isTesting ? (
                            <ActivityIndicator size="small" color="#a1a1aa" />
                          ) : (
                            <AppIcon
                              icon={Wrench01Icon}
                              size={15}
                              color="#a1a1aa"
                            />
                          )}
                          <Text
                            style={{
                              color: "#a1a1aa",
                              fontSize: fontSize.sm,
                              fontWeight: "500",
                            }}
                          >
                            {isTesting ? "Testing..." : "Test Connection"}
                          </Text>
                        </Pressable>
                      )}
                    </View>

                    {/* ─── Test result banner ────────────────────────────── */}
                    {(isTesting || testResult || testError) && (
                      <TestResultBanner
                        isLoading={isTesting}
                        result={testResult}
                        error={testError}
                      />
                    )}

                    {/* ─── Tools list ────────────────────────────────────── */}
                    {tools.length > 0 && (
                      <View
                        style={{
                          backgroundColor: "rgba(255,255,255,0.04)",
                          borderRadius: moderateScale(14, 0.5),
                          padding: spacing.md,
                          gap: spacing.sm,
                        }}
                      >
                        <View
                          style={{
                            flexDirection: "row",
                            alignItems: "center",
                            justifyContent: "space-between",
                          }}
                        >
                          <View
                            style={{
                              flexDirection: "row",
                              alignItems: "center",
                              gap: spacing.sm,
                            }}
                          >
                            <AppIcon
                              icon={Wrench01Icon}
                              size={14}
                              color="#71717a"
                            />
                            <Text
                              style={{
                                fontSize: fontSize.xs,
                                fontWeight: "600",
                                color: "#71717a",
                                letterSpacing: 0.5,
                                textTransform: "uppercase",
                              }}
                            >
                              Available Tools
                            </Text>
                            <View
                              style={{
                                backgroundColor: "rgba(0,187,255,0.12)",
                                borderRadius: 999,
                                minWidth: 20,
                                height: 18,
                                alignItems: "center",
                                justifyContent: "center",
                                paddingHorizontal: 6,
                              }}
                            >
                              <Text
                                style={{
                                  fontSize: fontSize.xs - 1,
                                  color: "#00bbff",
                                  fontWeight: "600",
                                }}
                              >
                                {tools.length}
                              </Text>
                            </View>
                          </View>
                        </View>

                        <View style={{ gap: 2 }}>
                          {visibleTools.map((tool) => (
                            <ToolItem
                              key={tool.name}
                              name={tool.name}
                              description={tool.description}
                            />
                          ))}
                        </View>

                        {hasMoreTools && (
                          <Pressable
                            onPress={() => setToolsExpanded((v) => !v)}
                            style={({ pressed }) => ({
                              paddingVertical: spacing.xs,
                              alignItems: "center",
                              opacity: pressed ? 0.7 : 1,
                            })}
                          >
                            <Text
                              style={{
                                fontSize: fontSize.xs,
                                color: "#00bbff",
                                fontWeight: "500",
                              }}
                            >
                              {toolsExpanded
                                ? "Show less"
                                : `Show ${tools.length - TOOLS_INITIAL_COUNT} more tools`}
                            </Text>
                          </Pressable>
                        )}
                      </View>
                    )}

                    {/* ─── Custom integration actions ────────────────────── */}
                    {isCustom && (
                      <View
                        style={{
                          gap: spacing.sm,
                          borderTopWidth: 1,
                          borderTopColor: "rgba(255,255,255,0.07)",
                          paddingTop: spacing.md,
                        }}
                      >
                        <Text
                          style={{
                            fontSize: fontSize.xs,
                            fontWeight: "600",
                            color: "#71717a",
                            letterSpacing: 0.5,
                            textTransform: "uppercase",
                          }}
                        >
                          Manage
                        </Text>
                        <View style={{ flexDirection: "row", gap: spacing.sm }}>
                          <Pressable
                            onPress={handleEdit}
                            style={({ pressed }) => ({
                              flex: 1,
                              flexDirection: "row",
                              alignItems: "center",
                              justifyContent: "center",
                              gap: spacing.xs,
                              padding: spacing.md,
                              borderRadius: moderateScale(12, 0.5),
                              backgroundColor: pressed
                                ? "rgba(255,255,255,0.07)"
                                : "rgba(255,255,255,0.04)",
                              borderWidth: 1,
                              borderColor: "rgba(255,255,255,0.1)",
                            })}
                          >
                            <AppIcon
                              icon={Edit02Icon}
                              size={14}
                              color="#a1a1aa"
                            />
                            <Text
                              style={{
                                fontSize: fontSize.sm,
                                color: "#a1a1aa",
                                fontWeight: "500",
                              }}
                            >
                              Edit
                            </Text>
                          </Pressable>

                          <Pressable
                            onPress={handleDelete}
                            disabled={isDeleting}
                            style={({ pressed }) => ({
                              flex: 1,
                              flexDirection: "row",
                              alignItems: "center",
                              justifyContent: "center",
                              gap: spacing.xs,
                              padding: spacing.md,
                              borderRadius: moderateScale(12, 0.5),
                              backgroundColor: pressed
                                ? "rgba(239,68,68,0.12)"
                                : "rgba(239,68,68,0.07)",
                              borderWidth: 1,
                              borderColor: "rgba(239,68,68,0.2)",
                              opacity: isDeleting ? 0.6 : 1,
                            })}
                          >
                            {isDeleting ? (
                              <ActivityIndicator size="small" color="#ef4444" />
                            ) : (
                              <AppIcon
                                icon={Delete02Icon}
                                size={14}
                                color="#ef4444"
                              />
                            )}
                            <Text
                              style={{
                                fontSize: fontSize.sm,
                                color: "#ef4444",
                                fontWeight: "500",
                              }}
                            >
                              Delete
                            </Text>
                          </Pressable>
                        </View>
                      </View>
                    )}
                  </>
                );
              })()}
            </BottomSheetScrollView>
          ) : null}
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

IntegrationDetailSheet.displayName = "IntegrationDetailSheet";
