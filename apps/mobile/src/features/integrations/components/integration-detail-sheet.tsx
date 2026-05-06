import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { ActivityIndicator, Alert, Pressable, View } from "react-native";
import {
  AppIcon,
  Delete02Icon,
  Edit02Icon,
  Wrench01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import {
  type TestConnectionResponse,
  testIntegrationConnection,
} from "../api/integrations-api";
import type { Integration } from "../types";
import { IntegrationDetailHeader } from "./IntegrationDetailHeader";
import { IntegrationToolsPanel } from "./IntegrationToolsPanel";
import { TestConnectionResult } from "./TestConnectionResult";

const DESCRIPTION_PREVIEW_LIMIT = 120;

export interface IntegrationDetailSheetRef {
  open: (integration: Integration) => void;
  close: () => void;
}

interface IntegrationDetailSheetProps {
  onConnect?: (integration: Integration) => void | Promise<void>;
  onDisconnect?: (integration: Integration) => void | Promise<void>;
  onEdit?: (integration: Integration) => void;
  onDelete?: (integration: Integration) => void | Promise<void>;
  onPublish?: (integration: Integration) => void | Promise<void>;
  onUnpublish?: (integration: Integration) => void | Promise<void>;
  onTest?: (integration: Integration) => void;
}

export const IntegrationDetailSheet = forwardRef<
  IntegrationDetailSheetRef,
  IntegrationDetailSheetProps
>(({ onConnect, onDisconnect, onEdit, onDelete }, ref) => {
  const { spacing, fontSize, moderateScale } = useResponsive();

  const [isOpen, setIsOpen] = useState(false);
  const [integration, setIntegration] = useState<Integration | null>(null);

  const [descExpanded, setDescExpanded] = useState(false);
  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestConnectionResponse | null>(
    null,
  );
  const [testError, setTestError] = useState<string | null>(null);

  const snapPoints = useMemo(() => ["60%", "90%"], []);

  const reset = useCallback(() => {
    setDescExpanded(false);
    setIsConnecting(false);
    setIsDisconnecting(false);
    setIsDeleting(false);
    setIsTesting(false);
    setTestResult(null);
    setTestError(null);
  }, []);

  useImperativeHandle(ref, () => ({
    open: (next: Integration) => {
      setIntegration(next);
      reset();
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const handleConnect = useCallback(async () => {
    if (!integration || !onConnect) return;
    setIsConnecting(true);
    try {
      await onConnect(integration);
    } finally {
      setIsConnecting(false);
    }
    setIsOpen(false);
  }, [integration, onConnect]);

  const handleDisconnect = useCallback(() => {
    if (!integration || !onDisconnect) return;
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
              await onDisconnect(integration);
            } finally {
              setIsDisconnecting(false);
            }
            setIsOpen(false);
          },
        },
      ],
    );
  }, [integration, onDisconnect]);

  const handleTest = useCallback(async () => {
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

  const handleEdit = useCallback(() => {
    if (!integration || !onEdit) return;
    onEdit(integration);
    setIsOpen(false);
  }, [integration, onEdit]);

  const handleDelete = useCallback(() => {
    if (!integration || !onDelete) return;
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
              await onDelete(integration);
            } finally {
              setIsDeleting(false);
            }
            setIsOpen(false);
          },
        },
      ],
    );
  }, [integration, onDelete]);

  if (!integration) {
    return null;
  }

  const isConnected = integration.status === "connected";
  const isError = integration.status === "error";
  const isCustom = integration.source === "custom";
  const tools = integration.tools ?? [];
  const descriptionIsLong =
    integration.description.length > DESCRIPTION_PREVIEW_LIMIT;
  const displayedDescription =
    descExpanded || !descriptionIsLong
      ? integration.description
      : `${integration.description.slice(0, DESCRIPTION_PREVIEW_LIMIT)}...`;

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={snapPoints}
          enableDynamicSizing={false}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#111111" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          <BottomSheetScrollView
            contentContainerStyle={{
              padding: spacing.lg,
              gap: spacing.lg,
              paddingBottom: spacing.xl * 2,
            }}
          >
            <IntegrationDetailHeader integration={integration} />

            {integration.description ? (
              <View style={{ gap: spacing.xs }}>
                <Text
                  className="text-zinc-400"
                  style={{ fontSize: fontSize.sm, lineHeight: 20 }}
                >
                  {displayedDescription}
                </Text>
                {descriptionIsLong ? (
                  <Pressable
                    onPress={() => setDescExpanded((v) => !v)}
                    hitSlop={8}
                  >
                    <Text
                      className="text-primary"
                      style={{ fontSize: fontSize.xs, fontWeight: "500" }}
                    >
                      {descExpanded ? "Show less" : "Show more"}
                    </Text>
                  </Pressable>
                ) : null}
              </View>
            ) : null}

            {/* Primary connect / disconnect action */}
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
                    className="text-red-500"
                    style={{ fontSize: fontSize.sm, fontWeight: "600" }}
                  >
                    {isDisconnecting ? "Disconnecting..." : "Disconnect"}
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
                    {isConnecting ? "Connecting..." : "Connect"}
                  </Text>
                </Pressable>
              )}

              {isConnected ? (
                <Pressable
                  onPress={handleTest}
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
                    <AppIcon icon={Wrench01Icon} size={15} color="#a1a1aa" />
                  )}
                  <Text
                    className="text-zinc-400"
                    style={{ fontSize: fontSize.sm, fontWeight: "500" }}
                  >
                    {isTesting ? "Testing..." : "Test Connection"}
                  </Text>
                </Pressable>
              ) : null}
            </View>

            {isTesting || testResult || testError ? (
              <TestConnectionResult
                isLoading={isTesting}
                result={testResult}
                error={testError}
              />
            ) : null}

            <IntegrationToolsPanel tools={tools} />

            {isCustom ? (
              <View
                style={{
                  gap: spacing.sm,
                  borderTopWidth: 1,
                  borderTopColor: "rgba(255,255,255,0.07)",
                  paddingTop: spacing.md,
                }}
              >
                <Text
                  className="uppercase tracking-wider text-zinc-500"
                  style={{ fontSize: fontSize.xs, fontWeight: "600" }}
                >
                  Manage
                </Text>
                <View style={{ flexDirection: "row", gap: spacing.sm }}>
                  {onEdit ? (
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
                      <AppIcon icon={Edit02Icon} size={14} color="#a1a1aa" />
                      <Text
                        className="text-zinc-400"
                        style={{ fontSize: fontSize.sm, fontWeight: "500" }}
                      >
                        Edit
                      </Text>
                    </Pressable>
                  ) : null}

                  {onDelete ? (
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
                        className="text-red-500"
                        style={{ fontSize: fontSize.sm, fontWeight: "500" }}
                      >
                        Delete
                      </Text>
                    </Pressable>
                  ) : null}
                </View>
              </View>
            ) : null}
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

IntegrationDetailSheet.displayName = "IntegrationDetailSheet";
