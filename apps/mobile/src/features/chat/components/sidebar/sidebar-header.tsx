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
  const { spacing, fontSize, iconSize } = useResponsive();

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
            placeholderTextColor="#71717a"
            value={searchQuery}
            onChangeText={onSearchChange}
            style={{
              fontSize: fontSize.md,
              color: "#e4e4e7",
              backgroundColor: "#27272a",
              borderRadius: 8,
              paddingHorizontal: spacing.md,
              paddingVertical: spacing.sm,
              paddingLeft: spacing.xl,
              paddingRight: searchQuery.length > 0 ? spacing.xl : spacing.md,
              lineHeight: Math.round(fontSize.md * 1.5),
            }}
          />
          <View
            style={{
              position: "absolute",
              left: spacing.sm + 4,
              top: 0,
              bottom: 0,
              justifyContent: "center",
            }}
            pointerEvents="none"
          >
            <AppIcon
              icon={Search01Icon}
              size={iconSize.sm - 1}
              color="#71717a"
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
                width: spacing.xl,
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
