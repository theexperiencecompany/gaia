import { PressableFeedback } from "heroui-native";
import { View } from "react-native";
import {
  BubbleChatAddIcon,
  HugeiconsIcon,
  Menu01Icon,
  Search01Icon,
} from "@/components/icons";
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
        <View style={{ padding: moderateScale(4, 0.5) }}>
          <HugeiconsIcon icon={Menu01Icon} size={iconSize.lg} color="#ffffff" />
        </View>
      </PressableFeedback>

      <View style={{ flexDirection: "row", gap: spacing.sm }}>
        {onSearchPress && (
          <PressableFeedback onPress={onSearchPress}>
            <View style={{ padding: moderateScale(4, 0.5) }}>
              <HugeiconsIcon
                icon={Search01Icon}
                size={iconSize.md - 2}
                color="#bbbbbb"
              />
            </View>
          </PressableFeedback>
        )}
        <PressableFeedback onPress={onNewChatPress}>
          <View style={{ padding: moderateScale(4, 0.5) }}>
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
