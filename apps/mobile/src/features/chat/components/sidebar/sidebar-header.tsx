import { Image } from "expo-image";
import { PressableFeedback } from "heroui-native";
import { TextInput, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  PencilEdit02Icon,
  Search01Icon,
} from "@/components/icons";
import { useResponsive } from "@/lib/responsive";

const GaiaLogo = require("@shared/assets/logo/logo.svg");

interface SidebarHeaderProps {
  onNewChat: () => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export function SidebarHeader({
  onNewChat,
  searchQuery,
  onSearchChange,
}: SidebarHeaderProps) {
  const { spacing, fontSize, iconSize, moderateScale } = useResponsive();

  return (
    <View>
      {/* Top bar: wordmark + new chat */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingHorizontal: spacing.md,
          paddingTop: spacing.md,
          paddingBottom: spacing.sm,
        }}
      >
        <Image
          source={GaiaLogo}
          style={{ width: 28, height: 28, borderRadius: 6 }}
          contentFit="contain"
        />
        {/* Min 44dp tap target: 12px padding + 16px icon = 40dp core, hitSlop adds remaining */}
        <PressableFeedback
          onPress={onNewChat}
          hitSlop={12}
          style={{
            padding: 10,
            borderRadius: 8,
            backgroundColor: "rgba(0,187,255,0.1)",
          }}
        >
          <AppIcon icon={PencilEdit02Icon} size={iconSize.sm} color="#00bbff" />
        </PressableFeedback>
      </View>

      {/* Search input */}
      <View
        style={{
          paddingHorizontal: spacing.md,
          paddingBottom: spacing.sm,
        }}
      >
        <View style={{ position: "relative" }}>
          <TextInput
            placeholder="Search conversations..."
            placeholderTextColor="#52525b"
            value={searchQuery}
            onChangeText={onSearchChange}
            style={{
              fontSize: fontSize.sm,
              color: "#e4e4e7",
              backgroundColor: "#18181b",
              borderRadius: 8,
              // 12px vertical padding + ~14px font = ~38dp, close enough on sidebar
              paddingHorizontal: moderateScale(12, 0.5),
              paddingVertical: 12,
              paddingLeft: moderateScale(36, 0.5),
              paddingRight:
                searchQuery.length > 0
                  ? moderateScale(36, 0.5)
                  : moderateScale(12, 0.5),
            }}
          />
          <View
            style={{
              position: "absolute",
              left: moderateScale(11, 0.5),
              top: 0,
              bottom: 0,
              justifyContent: "center",
            }}
            pointerEvents="none"
          >
            <AppIcon
              icon={Search01Icon}
              size={iconSize.sm - 1}
              color={searchQuery.length > 0 ? "#71717a" : "#52525b"}
            />
          </View>
          {searchQuery.length > 0 && (
            <PressableFeedback
              onPress={() => onSearchChange("")}
              hitSlop={8}
              style={{
                position: "absolute",
                right: 0,
                top: 0,
                bottom: 0,
                width: moderateScale(36, 0.5),
                justifyContent: "center",
                alignItems: "center",
              }}
            >
              <AppIcon
                icon={Cancel01Icon}
                size={iconSize.sm - 2}
                color="#71717a"
              />
            </PressableFeedback>
          )}
        </View>
      </View>
    </View>
  );
}
