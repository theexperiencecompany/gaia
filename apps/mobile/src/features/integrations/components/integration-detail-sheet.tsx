import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useMemo,
  useState,
} from "react";
import { ActivityIndicator, Alert, Pressable, View } from "react-native";
import { AppIcon, Delete02Icon, Edit02Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type { Integration } from "../types";
import { IntegrationDetailHeader } from "./IntegrationDetailHeader";
import { IntegrationToolsPanel } from "./IntegrationToolsPanel";

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
}

export const IntegrationDetailSheet = forwardRef<
  IntegrationDetailSheetRef,
  IntegrationDetailSheetProps
>(({ onConnect, onDisconnect, onEdit, onDelete }, ref) => {
  const { spacing, fontSize, moderateScale } = useResponsive();

  const [isOpen, setIsOpen] = useState(false);
  const [integration, setIntegration] = useState<Integration | null>(null);

  const [isConnecting, setIsConnecting] = useState(false);
  const [isDisconnecting, setIsDisconnecting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const snapPoints = useMemo(() => ["60%", "90%"], []);

  const reset = useCallback(() => {
    setIsConnecting(false);
    setIsDisconnecting(false);
    setIsDeleting(false);
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
  const showRetry = integration.status === "created";
  const isCustom = integration.source === "custom";
  const tools = integration.tools ?? [];

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
              paddingHorizontal: spacing.lg,
              paddingTop: spacing.md,
              paddingBottom: spacing.xl * 2,
              gap: spacing.md,
            }}
          >
            <IntegrationDetailHeader integration={integration} />

            {integration.description ? (
              <Text
                className="text-zinc-400"
                style={{
                  fontSize: fontSize.sm,
                  lineHeight: 20,
                  fontWeight: "300",
                }}
              >
                {integration.description}
              </Text>
            ) : null}

            {/* Primary connect / disconnect action */}
            {isConnected || isError ? (
              <Pressable
                onPress={handleDisconnect}
                disabled={isDisconnecting}
                style={({ pressed }) => ({
                  paddingVertical: spacing.sm + 2,
                  paddingHorizontal: spacing.md,
                  borderRadius: moderateScale(12, 0.5),
                  backgroundColor: pressed
                    ? "rgba(239,68,68,0.20)"
                    : "rgba(239,68,68,0.12)",
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
                  paddingVertical: spacing.sm + 2,
                  paddingHorizontal: spacing.md,
                  borderRadius: moderateScale(12, 0.5),
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
                    fontWeight: "600",
                  }}
                >
                  {isConnecting
                    ? "Connecting..."
                    : showRetry
                      ? "Retry Connection"
                      : "Connect"}
                </Text>
              </Pressable>
            )}

            <IntegrationToolsPanel
              tools={tools}
              categoryPrefix={integration.name}
            />

            {isCustom ? (
              <View
                style={{
                  flexDirection: "row",
                  gap: spacing.sm,
                  marginTop: spacing.xs,
                }}
              >
                {onEdit ? (
                  <Pressable
                    onPress={handleEdit}
                    style={({ pressed }) => ({
                      flex: 1,
                      flexDirection: "row",
                      alignItems: "center",
                      justifyContent: "center",
                      gap: spacing.xs,
                      padding: spacing.sm + 2,
                      borderRadius: moderateScale(10, 0.5),
                      backgroundColor: pressed
                        ? "rgba(255,255,255,0.07)"
                        : "rgba(255,255,255,0.04)",
                    })}
                  >
                    <AppIcon icon={Edit02Icon} size={14} color="#a1a1aa" />
                    <Text
                      className="text-zinc-300"
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
                      padding: spacing.sm + 2,
                      borderRadius: moderateScale(10, 0.5),
                      backgroundColor: pressed
                        ? "rgba(239,68,68,0.10)"
                        : "rgba(239,68,68,0.06)",
                      opacity: isDeleting ? 0.6 : 1,
                    })}
                  >
                    {isDeleting ? (
                      <ActivityIndicator size="small" color="#ef4444" />
                    ) : (
                      <AppIcon icon={Delete02Icon} size={14} color="#ef4444" />
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
            ) : null}
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

IntegrationDetailSheet.displayName = "IntegrationDetailSheet";
