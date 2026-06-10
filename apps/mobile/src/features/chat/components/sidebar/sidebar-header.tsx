import { Image } from "expo-image";
import { PressableFeedback } from "heroui-native";
import { TextInput, View } from "react-native";
import {
  AppIcon,
  Cancel01Icon,
  PencilEdit02Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

const GaiaLogo = require("@shared/assets/logo/logo.svg");

interface SidebarHeaderProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  onNewChat?: () => void;
}

const SECTION_PADDING = 12;

export function SidebarHeader({
  searchQuery,
  onSearchChange,
  onNewChat,
}: SidebarHeaderProps) {
  const { spacing, fontSize, iconSize } = useResponsive();

  return (
    <View>
      {/* Brand row: logo + wordmark + new chat button */}
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: SECTION_PADDING,
          paddingTop: spacing.md,
          paddingBottom: spacing.sm,
          gap: 10,
        }}
      >
        <Image
          source={GaiaLogo}
          style={{ width: 28, height: 28 }}
          contentFit="contain"
        />
        <Text
          style={{
            fontSize: fontSize.lg,
            fontWeight: "600",
            color: "#e4e4e7",
            letterSpacing: 0.2,
            flex: 1,
          }}
        >
          GAIA
        </Text>
        <PressableFeedback onPress={onNewChat} hitSlop={8}>
          <AppIcon icon={PencilEdit02Icon} size={iconSize.md} color="#a1a1aa" />
        </PressableFeedback>
      </View>

      {/* Search input — edge-to-edge with same horizontal padding as other sections */}
      <View
        style={{
          paddingHorizontal: SECTION_PADDING,
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
              borderRadius: 10,
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
              left: spacing.sm + 2,
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
