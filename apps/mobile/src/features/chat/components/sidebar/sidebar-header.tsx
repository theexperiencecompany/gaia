import { Button } from "heroui-native";
import { Image, Text, TextInput, View } from "react-native";
import {
  HugeiconsIcon,
  PencilEdit02Icon,
  Search01Icon,
} from "@/components/icons";
import { useResponsive } from "@/lib/responsive";

interface SidebarHeaderProps {
  onNewChat: () => void;
}

export function SidebarHeader({ onNewChat }: SidebarHeaderProps) {
  const { spacing, fontSize, iconSize, moderateScale } = useResponsive();

  return (
    <View
      style={{
        paddingHorizontal: spacing.md,
        paddingTop: spacing.lg,
        paddingBottom: spacing.md,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: moderateScale(12, 0.5),
          marginBottom: spacing.lg,
          paddingHorizontal: spacing.xs,
        }}
      >
        <Image
          source={require("@shared/assets/logo/logo.webp")}
          style={{
            width: moderateScale(28, 0.5),
            height: moderateScale(28, 0.5),
          }}
          resizeMode="contain"
        />
        <Text
          style={{
            fontSize: fontSize.xl,
            fontWeight: "bold",
            letterSpacing: -0.5,
            color: "#ffffff",
          }}
        >
          GAIA
        </Text>
      </View>

      <View style={{ flexDirection: "row", alignItems: "center" }}>
        <View
          style={{
            flex: 1,
            flexDirection: "row",
            alignItems: "center",
            backgroundColor: "#1c1c1e",
            borderRadius: moderateScale(12, 0.5),
            paddingHorizontal: moderateScale(12, 0.5),
            paddingVertical: spacing.sm,
          }}
        >
          <HugeiconsIcon
            icon={Search01Icon}
            size={iconSize.sm}
            color="#8e8e93"
          />
          <TextInput
            placeholder="Search"
            placeholderTextColor="#8e8e93"
            style={{
              flex: 1,
              marginLeft: spacing.sm,
              fontSize: fontSize.sm,
              color: "#ffffff",
            }}
          />
        </View>

        <Button
          variant="secondary"
          size="sm"
          style={{ marginLeft: spacing.sm }}
          isIconOnly
          onPress={onNewChat}
        >
          <HugeiconsIcon
            icon={PencilEdit02Icon}
            size={iconSize.sm}
            color="#ffffff"
          />
        </Button>
      </View>
    </View>
  );
}
