import { Button, Card, PressableFeedback, Spinner } from "heroui-native";
import {
  Image,
  KeyboardAvoidingView,
  Linking,
  Platform,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
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
  onSubmit: () => void;
  onFooterLinkPress: () => void;
}

export function AuthScreen({
  title,
  buttonLabel,
  footerQuestion,
  footerLinkLabel,
  isLoading,
  onSubmit,
  onFooterLinkPress,
}: AuthScreenProps) {
  const { spacing, fontSize, moderateScale, width } = useResponsive();
  const cardMaxWidth = Math.min(width * 0.9, 400);
  const logoSize = moderateScale(48, 0.5);
  const logoContainerSize = moderateScale(72, 0.5);

  return (
    <View style={{ flex: 1, backgroundColor: "#060a14" }}>
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
          backgroundColor: "rgba(0,0,0,0.5)",
        }}
      />

      <SafeAreaView style={{ flex: 1 }}>
        <KeyboardAvoidingView
          style={{
            flex: 1,
            justifyContent: "center",
            alignItems: "center",
            paddingHorizontal: spacing.lg,
          }}
          behavior={Platform.OS === "ios" ? "padding" : "height"}
        >
          <Card
            variant="secondary"
            className="w-full overflow-hidden rounded-[24px] bg-[#171920]/95"
            style={{ maxWidth: cardMaxWidth, width: "100%" }}
          >
            <Card.Body
              style={{
                paddingHorizontal: spacing.xl,
                paddingVertical: moderateScale(40, 0.5),
              }}
            >
              {/* Logo + Title */}
              <View style={{ alignItems: "center", marginBottom: spacing.xl }}>
                <View
                  style={{
                    width: logoContainerSize,
                    height: logoContainerSize,
                    borderRadius: logoContainerSize / 2,
                    alignItems: "center",
                    justifyContent: "center",
                    marginBottom: spacing.md,
                  }}
                >
                  <Image
                    source={gaiaLogoSource}
                    style={{ width: logoSize, height: logoSize }}
                    resizeMode="contain"
                  />
                </View>
                <Text
                  style={{
                    fontSize: fontSize["2xl"],
                    fontWeight: "bold",
                    textAlign: "center",
                  }}
                >
                  {title}
                </Text>
              </View>

              {/* Google Button */}
              <View style={{ width: "100%" }}>
                <Button
                  size="lg"
                  className="bg-white"
                  isDisabled={isLoading}
                  onPress={onSubmit}
                >
                  {isLoading ? (
                    <Spinner color="#000000" size="sm" />
                  ) : (
                    <>
                      <Image
                        source={googleLogoSource}
                        style={{
                          width: moderateScale(20, 0.5),
                          height: moderateScale(20, 0.5),
                          marginRight: spacing.sm,
                        }}
                        resizeMode="contain"
                      />
                      <Button.Label className="text-black">
                        {buttonLabel}
                      </Button.Label>
                    </>
                  )}
                </Button>

                {/* Switch screen link */}
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "center",
                    marginTop: spacing.md,
                  }}
                >
                  <Text style={{ fontSize: fontSize.base, color: "#8e8e93" }}>
                    {footerQuestion}{" "}
                  </Text>
                  <PressableFeedback
                    onPress={onFooterLinkPress}
                    isDisabled={isLoading}
                  >
                    <Text
                      style={{
                        fontSize: fontSize.base,
                        color: "#00bbff",
                        fontWeight: "600",
                      }}
                    >
                      {footerLinkLabel}
                    </Text>
                  </PressableFeedback>
                </View>
              </View>

              {/* Legal footer */}
              <View
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  justifyContent: "center",
                  marginTop: spacing.lg,
                  flexWrap: "wrap",
                }}
              >
                <PressableFeedback
                  onPress={() => Linking.openURL("https://heygaia.io/terms")}
                >
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      color: "#8e8e93",
                      textDecorationLine: "underline",
                    }}
                  >
                    Terms of Service
                  </Text>
                </PressableFeedback>
                <Text
                  style={{
                    fontSize: fontSize.sm,
                    color: "#8e8e93",
                    marginHorizontal: spacing.xs,
                  }}
                >
                  and
                </Text>
                <PressableFeedback
                  onPress={() => Linking.openURL("https://heygaia.io/privacy")}
                >
                  <Text
                    style={{
                      fontSize: fontSize.sm,
                      color: "#8e8e93",
                      textDecorationLine: "underline",
                    }}
                  >
                    Privacy Policy
                  </Text>
                </PressableFeedback>
              </View>
            </Card.Body>
          </Card>
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}
