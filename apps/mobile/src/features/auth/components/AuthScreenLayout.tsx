import type { ReactNode } from "react";
import {
  Image,
  type ImageSourcePropType,
  KeyboardAvoidingView,
  Platform,
  View,
} from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useResponsive } from "@/lib/responsive";

interface AuthScreenLayoutProps {
  backgroundSource: ImageSourcePropType;
  children: ReactNode;
}

export function AuthScreenLayout({
  backgroundSource,
  children,
}: AuthScreenLayoutProps) {
  const { spacing } = useResponsive();

  return (
    <View style={{ flex: 1, backgroundColor: "#0a0a0a" }}>
      <Image
        source={backgroundSource}
        style={{ position: "absolute", width: "100%", height: "100%" }}
        resizeMode="cover"
        blurRadius={0.5}
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
          {children}
        </KeyboardAvoidingView>
      </SafeAreaView>
    </View>
  );
}

interface AuthLogoProps {
  marginBottom?: number;
}

export function AuthLogo({ marginBottom }: AuthLogoProps) {
  const { spacing, moderateScale } = useResponsive();
  const logoSize = moderateScale(48, 0.5);
  const logoContainerSize = moderateScale(72, 0.5);

  return (
    <View
      style={{
        width: logoContainerSize,
        height: logoContainerSize,
        borderRadius: logoContainerSize / 2,
        backgroundColor: "rgba(0,187,255,0.15)",
        alignItems: "center",
        justifyContent: "center",
        marginBottom: marginBottom ?? spacing.md,
      }}
    >
      <Image
        source={require("@shared/assets/logo/logo.webp")}
        style={{ width: logoSize, height: logoSize }}
        resizeMode="contain"
      />
    </View>
  );
}

interface AuthCardProps {
  children: ReactNode;
}

export function AuthCard({ children }: AuthCardProps) {
  const { moderateScale, spacing, width } = useResponsive();
  const cardMaxWidth = Math.min(width * 0.9, 400);

  return (
    <View
      style={{
        width: "100%",
        maxWidth: cardMaxWidth,
        backgroundColor: "rgba(28,28,30,0.95)",
        borderRadius: moderateScale(24, 0.5),
        paddingHorizontal: spacing.xl,
        paddingVertical: moderateScale(40, 0.5),
        borderWidth: 1,
        borderColor: "rgba(255,255,255,0.1)",
      }}
    >
      {children}
    </View>
  );
}
