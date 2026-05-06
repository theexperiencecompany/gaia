import {
  BottomSheetScrollView,
  BottomSheetTextInput,
} from "@gorhom/bottom-sheet";
import { Image } from "expo-image";
import * as Linking from "expo-linking";
import { forwardRef, useCallback, useImperativeHandle, useState } from "react";
import { ActivityIndicator, Pressable, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  LinkSquare02Icon,
  ShieldUserIcon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BottomSheet } from "@/shared/components/ui/bottom-sheet";
import { connectIntegrationWithToken } from "../api/integrations-api";
import { getIntegrationLogo } from "../constants/logos";

export interface BearerTokenSheetConfig {
  integrationId: string;
  integrationName: string;
  iconUrl?: string;
  docsUrl?: string;
}

export interface BearerTokenSheetRef {
  open: (config: BearerTokenSheetConfig) => void;
  close: () => void;
}

interface BearerTokenSheetProps {
  onSuccess?: (integrationId: string) => void;
}

export const BearerTokenSheet = forwardRef<
  BearerTokenSheetRef,
  BearerTokenSheetProps
>(({ onSuccess }, ref) => {
  const { fontSize, spacing, moderateScale } = useResponsive();

  const [isOpen, setIsOpen] = useState(false);
  const [config, setConfig] = useState<BearerTokenSheetConfig | null>(null);
  const [token, setToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSuccess, setIsSuccess] = useState(false);

  useImperativeHandle(ref, () => ({
    open: (cfg: BearerTokenSheetConfig) => {
      setConfig(cfg);
      setToken("");
      setShowToken(false);
      setError(null);
      setIsLoading(false);
      setIsSuccess(false);
      setIsOpen(true);
    },
    close: () => setIsOpen(false),
  }));

  const handleDismiss = useCallback(() => {
    setToken("");
    setShowToken(false);
    setError(null);
    setIsLoading(false);
    setIsSuccess(false);
    setConfig(null);
  }, []);

  const handleConnect = useCallback(async () => {
    if (!config || !token.trim() || isLoading) return;

    setIsLoading(true);
    setError(null);

    const result = await connectIntegrationWithToken(
      config.integrationId,
      token.trim(),
    );

    if (result.success) {
      setIsLoading(false);
      setIsSuccess(true);
      onSuccess?.(config.integrationId);
      setTimeout(() => {
        setIsOpen(false);
      }, 1200);
    } else {
      setIsLoading(false);
      setError(result.error ?? "Connection failed. Please check your token.");
    }
  }, [config, token, isLoading, onSuccess]);

  const handleOpenDocs = useCallback(() => {
    if (config?.docsUrl) {
      void Linking.openURL(config.docsUrl);
    }
  }, [config?.docsUrl]);

  const logoUri = config
    ? getIntegrationLogo(config.integrationId, config.iconUrl)
    : null;

  const inputStyle = {
    flex: 1,
    color: "#f4f4f5",
    fontSize: fontSize.sm,
    padding: 0,
  };

  return (
    <BottomSheet
      isOpen={isOpen}
      onOpenChange={(open) => {
        setIsOpen(open);
        if (!open) handleDismiss();
      }}
    >
      <BottomSheet.Portal>
        <BottomSheet.Overlay />
        <BottomSheet.Content
          snapPoints={["55%"]}
          enableDynamicSizing={false}
          enablePanDownToClose={!isLoading}
          backgroundStyle={{ backgroundColor: "#131416" }}
          handleIndicatorStyle={{ backgroundColor: "#3a3a3c", width: 40 }}
        >
          {/* ─── Header ─────────────────────────────────────────────────────── */}
          <View
            style={{
              flexDirection: "row",
              alignItems: "center",
              justifyContent: "space-between",
              paddingHorizontal: spacing.md,
              paddingBottom: spacing.md,
              borderBottomWidth: 1,
              borderBottomColor: "rgba(255,255,255,0.06)",
            }}
          >
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                gap: spacing.sm,
              }}
            >
              {logoUri ? (
                <View
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: moderateScale(10, 0.5),
                    backgroundColor: "rgba(255,255,255,0.06)",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <Image
                    source={{ uri: logoUri }}
                    style={{ width: 24, height: 24 }}
                    contentFit="contain"
                  />
                </View>
              ) : (
                <View
                  style={{
                    width: 36,
                    height: 36,
                    borderRadius: moderateScale(10, 0.5),
                    backgroundColor: "rgba(0,187,255,0.12)",
                    alignItems: "center",
                    justifyContent: "center",
                  }}
                >
                  <AppIcon icon={ShieldUserIcon} size={18} color="#00bbff" />
                </View>
              )}
              <View style={{ gap: 2 }}>
                <Text
                  style={{
                    fontSize: fontSize.base,
                    fontWeight: "600",
                    color: "#fff",
                  }}
                >
                  Connect {config?.integrationName ?? "Integration"}
                </Text>
                <Text style={{ fontSize: fontSize.xs, color: "#71717a" }}>
                  API key / Bearer token required
                </Text>
              </View>
            </View>

            <Pressable
              onPress={() => setIsOpen(false)}
              disabled={isLoading}
              style={{
                width: 32,
                height: 32,
                borderRadius: 999,
                backgroundColor: "rgba(255,255,255,0.06)",
                alignItems: "center",
                justifyContent: "center",
                opacity: isLoading ? 0.4 : 1,
              }}
            >
              <AppIcon icon={Cancel01Icon} size={16} color="#71717a" />
            </Pressable>
          </View>

          <BottomSheetScrollView
            contentContainerStyle={{
              padding: spacing.md,
              gap: spacing.md,
              paddingBottom: spacing.xl * 2,
            }}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {/* Success state */}
            {isSuccess && (
              <View
                style={{
                  backgroundColor: "rgba(34,197,94,0.08)",
                  borderRadius: moderateScale(12, 0.5),
                  borderWidth: 1,
                  borderColor: "rgba(34,197,94,0.25)",
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.md,
                  alignItems: "center",
                  gap: 4,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: "#22c55e",
                    fontWeight: "600",
                  }}
                >
                  Connected successfully!
                </Text>
                <Text style={{ fontSize: fontSize.xs, color: "#86efac" }}>
                  {config?.integrationName ?? "Integration"} is now connected.
                </Text>
              </View>
            )}

            {/* Instructions */}
            {!isSuccess && (
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "#a1a1aa",
                  lineHeight: 20,
                }}
              >
                Enter your API key for{" "}
                <Text style={{ color: "#f4f4f5", fontWeight: "500" }}>
                  {config?.integrationName ?? "this integration"}
                </Text>
                . You can find it in the integration&apos;s developer settings.
              </Text>
            )}

            {/* Docs link */}
            {!isSuccess && config?.docsUrl && (
              <Pressable
                onPress={handleOpenDocs}
                style={({ pressed }) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  opacity: pressed ? 0.6 : 1,
                })}
              >
                <AppIcon icon={LinkSquare02Icon} size={14} color="#00bbff" />
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#00bbff",
                    fontWeight: "500",
                  }}
                >
                  How to get your API key
                </Text>
              </Pressable>
            )}

            {/* Token Input */}
            {!isSuccess && (
              <View
                style={{
                  backgroundColor: "rgba(255,255,255,0.06)",
                  borderRadius: moderateScale(12, 0.5),
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.sm + 2,
                  gap: 4,
                  borderWidth: 1,
                  borderColor: error
                    ? "rgba(239,68,68,0.4)"
                    : token.trim()
                      ? "rgba(0,187,255,0.3)"
                      : "transparent",
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#71717a",
                    fontWeight: "500",
                  }}
                >
                  API Key / Bearer Token
                </Text>
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    gap: spacing.sm,
                  }}
                >
                  <AppIcon icon={ShieldUserIcon} size={15} color="#6f737c" />
                  <BottomSheetTextInput
                    style={inputStyle}
                    placeholder="sk-... or your API token"
                    placeholderTextColor="#6f737c"
                    value={token}
                    onChangeText={(v) => {
                      setToken(v);
                      if (error) setError(null);
                    }}
                    secureTextEntry={!showToken}
                    editable={!isLoading}
                    autoCapitalize="none"
                    autoCorrect={false}
                    returnKeyType="done"
                    onSubmitEditing={() => void handleConnect()}
                  />
                  <Pressable
                    onPress={() => setShowToken((s) => !s)}
                    hitSlop={8}
                    style={{ opacity: isLoading ? 0.4 : 1 }}
                    accessibilityRole="button"
                    accessibilityLabel={showToken ? "Hide token" : "Show token"}
                  >
                    <Text
                      style={{
                        fontSize: fontSize.xs,
                        color: "#a1a1aa",
                        fontWeight: "500",
                      }}
                    >
                      {showToken ? "Hide" : "Show"}
                    </Text>
                  </Pressable>
                </View>
              </View>
            )}

            {/* Inline error */}
            {!isSuccess && error && (
              <View
                style={{
                  backgroundColor: "rgba(239,68,68,0.08)",
                  borderRadius: moderateScale(10, 0.5),
                  borderWidth: 1,
                  borderColor: "rgba(239,68,68,0.2)",
                  paddingHorizontal: spacing.md,
                  paddingVertical: spacing.sm + 2,
                }}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "#ef4444",
                    lineHeight: 18,
                  }}
                >
                  {error}
                </Text>
              </View>
            )}

            {/* Connect Button */}
            {!isSuccess && (
              <Pressable
                onPress={() => void handleConnect()}
                disabled={isLoading || !token.trim()}
                style={({ pressed }) => ({
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  gap: 8,
                  paddingVertical: spacing.md,
                  borderRadius: moderateScale(12, 0.5),
                  backgroundColor:
                    !token.trim() || isLoading
                      ? "rgba(0,187,255,0.3)"
                      : pressed
                        ? "rgba(0,170,230,0.9)"
                        : "rgba(0,187,255,0.85)",
                })}
              >
                {isLoading ? (
                  <ActivityIndicator size="small" color="#fff" />
                ) : (
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      fontWeight: "600",
                      color: "#fff",
                    }}
                  >
                    Connect {config?.integrationName ?? ""}
                  </Text>
                )}
              </Pressable>
            )}
          </BottomSheetScrollView>
        </BottomSheet.Content>
      </BottomSheet.Portal>
    </BottomSheet>
  );
});

BearerTokenSheet.displayName = "BearerTokenSheet";
