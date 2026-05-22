import {
  ActivityIndicator,
  Image,
  Linking,
  Platform,
  Pressable,
  StatusBar,
  View,
} from "react-native";
import Animated, { FadeInDown, FadeOutUp } from "react-native-reanimated";
import { SafeAreaView } from "react-native-safe-area-context";
import { Alert01Icon, AppIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

const backgroundSource =
  process.env.NODE_ENV === "test"
    ? { uri: "auth-background" }
    : require("@/assets/background/bands_gradient_black.png");

const gaiaLogoSource =
  process.env.NODE_ENV === "test"
    ? { uri: "gaia-logo" }
    : require("@shared/assets/logo/logo.webp");

const googleLogoSource =
  process.env.NODE_ENV === "test"
    ? { uri: "google-logo" }
    : require("@/assets/icons/google-logo.png");

interface AuthScreenProps {
  title: string;
  buttonLabel: string;
  footerQuestion: string;
  footerLinkLabel: string;
  isLoading: boolean;
  errorMessage?: string | null;
  onSubmit: () => void;
  onFooterLinkPress: () => void;
}

export function AuthScreen({
  title,
  buttonLabel,
  footerQuestion,
  footerLinkLabel,
  isLoading,
  errorMessage,
  onSubmit,
  onFooterLinkPress,
}: AuthScreenProps) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  return (
    <View style={{ flex: 1, backgroundColor: "#111111" }}>
      <StatusBar
        barStyle="light-content"
        backgroundColor="transparent"
        translucent
      />
      <Image
        source={backgroundSource}
        style={{ position: "absolute", width: "100%", height: "100%" }}
        resizeMode="cover"
      />
      <View
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
          backgroundColor: "rgba(0,0,0,0.55)",
        }}
      />

      <SafeAreaView style={{ flex: 1 }}>
        <View
          style={{
            flex: 1,
            paddingHorizontal: spacing.xl,
            paddingBottom: spacing.xl,
          }}
        >
          {/* Top section — logo + title */}
          <View
            style={{
              flex: 1,
              alignItems: "center",
              justifyContent: "center",
              gap: spacing.md,
            }}
          >
            <View
              style={{
                width: moderateScale(80, 0.5),
                height: moderateScale(80, 0.5),
                borderRadius: moderateScale(20, 0.5),
                alignItems: "center",
                justifyContent: "center",
                backgroundColor: "rgba(255,255,255,0.05)",
              }}
            >
              <Image
                source={gaiaLogoSource}
                style={{
                  width: moderateScale(52, 0.5),
                  height: moderateScale(52, 0.5),
                }}
                resizeMode="contain"
              />
            </View>

            <View style={{ alignItems: "center", gap: spacing.sm }}>
              <Text
                style={{
                  fontSize: fontSize["3xl"],
                  fontWeight: "700",
                  color: "#ffffff",
                  textAlign: "center",
                  letterSpacing: -0.5,
                }}
              >
                {title}
              </Text>
              <Text
                style={{
                  fontSize: fontSize.base,
                  color: "rgba(255,255,255,0.45)",
                  textAlign: "center",
                  lineHeight: fontSize.base * 1.5,
                }}
              >
                Your personal AI, always one tap away.
              </Text>
            </View>
          </View>

          {/* Bottom section — error banner + button + footer */}
          <View style={{ gap: spacing.md }}>
            {errorMessage ? (
              <Animated.View
                key={errorMessage}
                entering={FadeInDown.duration(200)}
                exiting={FadeOutUp.duration(150)}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: spacing.sm,
                  backgroundColor: "rgba(239,68,68,0.12)",
                  borderRadius: 12,
                  paddingVertical: spacing.sm,
                  paddingHorizontal: spacing.md,
                }}
              >
                <AppIcon icon={Alert01Icon} size={18} color="#f87171" />
                <Text
                  style={{
                    flex: 1,
                    fontSize: fontSize.sm,
                    color: "#fca5a5",
                    lineHeight: fontSize.sm * 1.4,
                  }}
                >
                  {errorMessage}
                </Text>
              </Animated.View>
            ) : null}
            {/* Google sign-in button */}
            <Pressable
              onPress={onSubmit}
              disabled={isLoading}
              style={({ pressed }) => ({
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: spacing.sm,
                backgroundColor: pressed ? "#f0f0f0" : "#ffffff",
                borderRadius: 14,
                paddingVertical: moderateScale(16, 0.5),
                paddingHorizontal: spacing.xl,
                opacity: isLoading ? 0.7 : 1,
                ...Platform.select({
                  ios: {
                    shadowColor: "#000",
                    shadowOffset: { width: 0, height: 2 },
                    shadowOpacity: 0.15,
                    shadowRadius: 8,
                  },
                  android: { elevation: 4 },
                }),
              })}
            >
              {isLoading ? (
                <ActivityIndicator color="#1a1a1a" size="small" />
              ) : (
                <>
                  <Image
                    source={googleLogoSource}
                    style={{
                      width: moderateScale(20, 0.5),
                      height: moderateScale(20, 0.5),
                    }}
                    resizeMode="contain"
                  />
                  <Text
                    style={{
                      fontSize: fontSize.base,
                      fontWeight: "600",
                      color: "#1a1a1a",
                    }}
                  >
                    {buttonLabel}
                  </Text>
                </>
              )}
            </Pressable>

            {/* Toggle login/signup */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                gap: 4,
                paddingVertical: spacing.xs,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.sm,
                  color: "rgba(255,255,255,0.45)",
                }}
              >
                {footerQuestion}
              </Text>
              <Pressable onPress={onFooterLinkPress} disabled={isLoading}>
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: "#00bbff",
                    fontWeight: "600",
                  }}
                >
                  {footerLinkLabel}
                </Text>
              </Pressable>
            </View>

            {/* Legal links */}
            <View
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                flexWrap: "wrap",
                gap: 4,
              }}
            >
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "rgba(255,255,255,0.25)",
                }}
              >
                By continuing you agree to our
              </Text>
              <Pressable
                onPress={() => void Linking.openURL("https://heygaia.io/terms")}
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "rgba(255,255,255,0.4)",
                    textDecorationLine: "underline",
                  }}
                >
                  Terms
                </Text>
              </Pressable>
              <Text
                style={{
                  fontSize: fontSize.xs,
                  color: "rgba(255,255,255,0.25)",
                }}
              >
                and
              </Text>
              <Pressable
                onPress={() =>
                  void Linking.openURL("https://heygaia.io/privacy")
                }
              >
                <Text
                  style={{
                    fontSize: fontSize.xs,
                    color: "rgba(255,255,255,0.4)",
                    textDecorationLine: "underline",
                  }}
                >
                  Privacy Policy
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </SafeAreaView>
    </View>
  );
}
