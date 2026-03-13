import { Button, PressableFeedback, Surface } from "heroui-native";
import { Image, TextInput, View } from "react-native";
import {
  AppIcon,
  ArrowLeft01Icon,
  Cancel01Icon,
  PencilEdit02Icon,
  Search01Icon,
} from "@/components/icons";
import { useResponsive } from "@/lib/responsive";

interface SidebarHeaderProps {
  onNewChat: () => void;
  onClose?: () => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
}

export function SidebarHeader({
  onNewChat,
  onClose,
  searchQuery,
  onSearchChange,
}: SidebarHeaderProps) {
  const { spacing, fontSize, iconSize, moderateScale } = useResponsive();

  return (
    <Surface
      variant="transparent"
      style={{
        paddingHorizontal: spacing.md,
        paddingTop: spacing.lg,
        paddingBottom: spacing.sm,
      }}
    >
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: moderateScale(12, 0.5),
          marginBottom: spacing.md,
          paddingHorizontal: spacing.xs,
        }}
      >
        {onClose ? (
          <PressableFeedback
            onPress={onClose}
            hitSlop={8}
            style={{ padding: 4 }}
          >
            <AppIcon
              icon={ArrowLeft01Icon}
              size={iconSize.sm}
              color="#a1a1aa"
            />
          </PressableFeedback>
        ) : (
          <Image
            source={require("@shared/assets/logo/logo.webp")}
            style={{
              width: moderateScale(28, 0.5),
              height: moderateScale(28, 0.5),
            }}
            resizeMode="contain"
          />
        )}
        <View style={{ flex: 1 }}>
          <TextInput
            placeholder="Search conversations..."
            placeholderTextColor="#6b6b6e"
            value={searchQuery}
            onChangeText={onSearchChange}
            style={{
              flex: 1,
              fontSize: fontSize.sm,
              color: "#ffffff",
              backgroundColor: "#1c1c1e",
              borderRadius: moderateScale(10, 0.5),
              paddingHorizontal: moderateScale(12, 0.5),
              paddingVertical: spacing.sm,
              paddingLeft: moderateScale(32, 0.5),
            }}
          />
          <View
            style={{
              position: "absolute",
              left: moderateScale(10, 0.5),
              top: 0,
              bottom: 0,
              justifyContent: "center",
            }}
            pointerEvents="none"
          >
            <AppIcon icon={Search01Icon} size={iconSize.sm} color="#6b6b6e" />
          </View>
          {searchQuery.length > 0 && (
            <PressableFeedback
              onPress={() => onSearchChange("")}
              style={{
                position: "absolute",
                right: moderateScale(8, 0.5),
                top: 0,
                bottom: 0,
                justifyContent: "center",
                paddingHorizontal: 4,
              }}
            >
              <AppIcon
                icon={Cancel01Icon}
                size={iconSize.sm - 2}
                color="#6b6b6e"
              />
            </PressableFeedback>
          )}
        </View>

        <Button variant="secondary" size="sm" isIconOnly onPress={onNewChat}>
          <AppIcon icon={PencilEdit02Icon} size={iconSize.sm} color="#ffffff" />
        </Button>
      </View>
    </Surface>
  );
}
