import { BottomSheetScrollView } from "@gorhom/bottom-sheet";
import { Image } from "expo-image";
import { forwardRef, useImperativeHandle, useState } from "react";
import { Pressable, TextInput, View } from "react-native";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import type { IntegrationWithStatus } from "../types";

export interface IntegrationDetailSheetRef {
  open: (integration: IntegrationWithStatus) => void;
  close: () => void;
}

interface IntegrationDetailSheetProps {
  onConnect: (integrationId: string, authType?: string, token?: string) => void;
  onDisconnect: (integrationId: string) => void;
}

export const IntegrationDetailSheet = forwardRef<
  IntegrationDetailSheetRef,
  IntegrationDetailSheetProps
>(({ onConnect, onDisconnect }, ref) => {
  const [isOpen, setIsOpen] = useState(false);
  const [integration, setIntegration] = useState<IntegrationWithStatus | null>(
    null,
  );
  const [bearerToken, setBearerToken] = useState("");
  const [showTokenInput, setShowTokenInput] = useState(false);
  const { spacing, fontSize } = useResponsive();

  useImperativeHandle(ref, () => ({
    open: (i: IntegrationWithStatus) => {
      setIntegration(i);
      setShowTokenInput(false);
      setBearerToken("");
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const handleConnect = () => {
    if (!integration) return;
    const authType = integration.authType ?? "oauth";
    if (authType === "bearer" && !showTokenInput) {
      setShowTokenInput(true);
      return;
    }
    onConnect(integration.id, authType, bearerToken || undefined);
    setIsOpen(false);
  };

  const handleDisconnect = () => {
    if (!integration) return;
    onDisconnect(integration.id);
    setIsOpen(false);
  };

  return (
    <BottomSheet isOpen={isOpen} onOpenChange={setIsOpen}>
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["50%", "80%"]}
          enablePanDownToClose
          backgroundStyle={{ backgroundColor: "#0b0c0f" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          {integration && (
            <BottomSheetScrollView
              contentContainerStyle={{ padding: spacing.lg, gap: spacing.md }}
            >
              {/* Header */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: spacing.md,
                }}
              >
                {integration.logo ? (
                  <Image
                    source={{ uri: integration.logo }}
                    style={{ width: 44, height: 44, borderRadius: 10 }}
                    contentFit="contain"
                  />
                ) : (
                  <View
                    style={{
                      width: 44,
                      height: 44,
                      borderRadius: 10,
                      backgroundColor: "#2c2c2e",
                      alignItems: "center",
                      justifyContent: "center",
                    }}
                  >
                    <Text style={{ fontSize: 20, color: "#a1a1aa" }}>
                      {(integration.name ?? "?")[0]}
                    </Text>
                  </View>
                )}
                <View style={{ flex: 1 }}>
                  <Text
                    style={{
                      fontSize: fontSize.base,
                      fontWeight: "600",
                      color: "#fff",
                    }}
                  >
                    {integration.name}
                  </Text>
                  <View
                    style={{
                      flexDirection: "row",
                      alignItems: "center",
                      gap: spacing.xs,
                      marginTop: 3,
                    }}
                  >
                    <View
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: 3,
                        backgroundColor: integration.connected
                          ? "#34c759"
                          : "#71717a",
                      }}
                    />
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: integration.connected ? "#34c759" : "#71717a",
                      }}
                    >
                      {integration.connected ? "Connected" : "Not connected"}
                    </Text>
                  </View>
                </View>
              </View>

              {/* Description */}
              {integration.description ? (
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: "#a1a1aa",
                    lineHeight: 20,
                  }}
                >
                  {integration.description}
                </Text>
              ) : null}

              {/* Tools provided */}
              {(integration.tools ?? []).length > 0 && (
                <View
                  style={{
                    gap: spacing.sm,
                    backgroundColor: "rgba(255,255,255,0.04)",
                    borderRadius: 12,
                    padding: spacing.md,
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
                    Tools Provided
                  </Text>
                  {(integration.tools ?? []).map((tool) => (
                    <View
                      key={tool.name}
                      style={{
                        flexDirection: "row",
                        alignItems: "flex-start",
                        gap: spacing.sm,
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
                          style={{ fontSize: fontSize.sm, color: "#e4e4e7" }}
                        >
                          {tool.name}
                        </Text>
                        {tool.description ? (
                          <Text
                            style={{
                              fontSize: fontSize.xs,
                              color: "#71717a",
                              marginTop: 1,
                            }}
                          >
                            {tool.description}
                          </Text>
                        ) : null}
                      </View>
                    </View>
                  ))}
                </View>
              )}

              {/* Bearer token input */}
              {showTokenInput && (
                <View style={{ gap: spacing.sm }}>
                  <Text style={{ fontSize: fontSize.sm, color: "#a1a1aa" }}>
                    Enter your API token:
                  </Text>
                  <TextInput
                    value={bearerToken}
                    onChangeText={setBearerToken}
                    placeholder="Bearer token..."
                    placeholderTextColor="#52525b"
                    secureTextEntry
                    autoFocus
                    style={{
                      borderWidth: 1,
                      borderColor: bearerToken
                        ? "rgba(0,187,255,0.4)"
                        : "#3f3f46",
                      borderRadius: 10,
                      padding: spacing.md,
                      color: "#fff",
                      fontSize: fontSize.sm,
                      backgroundColor: "#1c1c1e",
                    }}
                  />
                </View>
              )}

              {/* Action buttons */}
              <View
                style={{
                  flexDirection: "row",
                  gap: spacing.sm,
                  marginTop: spacing.sm,
                }}
              >
                {integration.connected ? (
                  <Pressable
                    onPress={handleDisconnect}
                    style={{
                      flex: 1,
                      padding: spacing.md,
                      borderRadius: 12,
                      backgroundColor: "rgba(239,68,68,0.1)",
                      borderWidth: 1,
                      borderColor: "rgba(239,68,68,0.3)",
                      alignItems: "center",
                    }}
                  >
                    <Text
                      style={{
                        color: "#ef4444",
                        fontSize: fontSize.sm,
                        fontWeight: "600",
                      }}
                    >
                      Disconnect
                    </Text>
                  </Pressable>
                ) : (
                  <Pressable
                    onPress={handleConnect}
                    style={{
                      flex: 1,
                      padding: spacing.md,
                      borderRadius: 12,
                      backgroundColor: "#00bbff",
                      alignItems: "center",
                    }}
                  >
                    <Text
                      style={{
                        color: "#000",
                        fontSize: fontSize.sm,
                        fontWeight: "600",
                      }}
                    >
                      {showTokenInput ? "Save Token" : "Connect"}
                    </Text>
                  </Pressable>
                )}
              </View>
            </BottomSheetScrollView>
          )}
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

IntegrationDetailSheet.displayName = "IntegrationDetailSheet";
