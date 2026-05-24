import { ActivityIndicator, Pressable, View } from "react-native";
import { AppIcon, Menu01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";
import { BackButton } from "@/shared/components/ui/back-button";
import { WORKFLOW_COLORS } from "../../constants/colors";

interface WorkflowDetailHeaderProps {
  title?: string;
  onBack: () => void;
  onMore?: () => void;
  showMore?: boolean;
  isWorking?: boolean;
}

export function WorkflowDetailHeader({
  title,
  onBack,
  onMore,
  showMore = false,
  isWorking = false,
}: WorkflowDetailHeaderProps) {
  const { spacing, fontSize } = useResponsive();

  return (
    <View
      style={{
        paddingTop: spacing.xl * 2,
        paddingHorizontal: spacing.md,
        paddingBottom: spacing.md,
        borderBottomWidth: 1,
        borderBottomColor: WORKFLOW_COLORS.borderSubtle,
        flexDirection: "row",
        alignItems: "center",
        gap: spacing.sm,
      }}
    >
      <BackButton onPress={onBack} hideWhenCannotGoBack={false} />

      {title ? (
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "600",
            color: WORKFLOW_COLORS.textPrimary,
            flex: 1,
          }}
          numberOfLines={1}
        >
          {title}
        </Text>
      ) : (
        <View style={{ flex: 1 }} />
      )}

      {showMore ? (
        <Pressable
          onPress={onMore}
          disabled={isWorking}
          hitSlop={8}
          style={{
            width: 36,
            height: 36,
            borderRadius: 999,
            alignItems: "center",
            justifyContent: "center",
            backgroundColor: WORKFLOW_COLORS.surfaceMuted,
          }}
        >
          {isWorking ? (
            <ActivityIndicator size="small" color={WORKFLOW_COLORS.textMuted} />
          ) : (
            <AppIcon
              icon={Menu01Icon}
              size={18}
              color={WORKFLOW_COLORS.textMuted}
            />
          )}
        </Pressable>
      ) : null}
    </View>
  );
}
