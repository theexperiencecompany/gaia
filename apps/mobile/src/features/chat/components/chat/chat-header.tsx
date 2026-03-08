import { PressableFeedback } from "heroui-native";
import { View } from "react-native";
import {
  BubbleChatAddIcon,
  HugeiconsIcon,
  Menu01Icon,
  Search01Icon,
} from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface ChatHeaderProps {
  onMenuPress: () => void;
  onNewChatPress: () => void;
  onSearchPress?: () => void;
}

export function ChatHeader({
  onMenuPress,
  onNewChatPress,
  onSearchPress,
}: ChatHeaderProps) {
  const { spacing, iconSize, moderateScale } = useResponsive();

  return (
    <View
      style={{
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        paddingHorizontal: spacing.lg,
        paddingVertical: spacing.md,
        backgroundColor: "transparent",
      }}
    >
      <PressableFeedback onPress={onMenuPress}>
        <View
          style={{
            padding: moderateScale(6, 0.5),
            borderRadius: moderateScale(10, 0.5),
            backgroundColor: "rgba(255,255,255,0.06)",
          }}
        >
          <HugeiconsIcon icon={Menu01Icon} size={iconSize.lg} color="#ffffff" />
        </View>
      </PressableFeedback>

      <Text className="text-sm font-semibold text-white/90">GAIA</Text>

      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        {onSearchPress && (
          <PressableFeedback onPress={onSearchPress}>
            <View
              style={{
                padding: moderateScale(6, 0.5),
                borderRadius: moderateScale(10, 0.5),
                backgroundColor: "rgba(255,255,255,0.06)",
              }}
            >
              <HugeiconsIcon
                icon={Search01Icon}
                size={iconSize.md - 2}
                color="#bbbbbb"
              />
            </View>
          </PressableFeedback>
        )}
        <PressableFeedback onPress={onNewChatPress}>
          <View
            style={{
              padding: moderateScale(6, 0.5),
              borderRadius: moderateScale(10, 0.5),
              backgroundColor: "rgba(255,255,255,0.06)",
            }}
          >
            <HugeiconsIcon
              icon={BubbleChatAddIcon}
              size={iconSize.md - 2}
              color="#bbbbbb"
            />
          </View>
        </PressableFeedback>
      </View>
    </View>
  );
}
