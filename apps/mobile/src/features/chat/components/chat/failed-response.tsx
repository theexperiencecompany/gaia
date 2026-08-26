import { Pressable, View } from "react-native";
import { Alert01Icon, AppIcon, RepeatIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { colors } from "@/lib/design-tokens";
import { useResponsive } from "@/lib/responsive";

// Gap scale tokens (decisions §5): 2/4/8/12/16/24.
const GAP_XS = 2;
const GAP_SM = 4;
const GAP_MD = 8;

function RetryButton({ onRetry }: { onRetry: () => void }) {
  const { moderateScale } = useResponsive();
  return (
    <Pressable
      onPress={onRetry}
      hitSlop={GAP_MD}
      style={({ pressed }) => ({
        flexDirection: "row",
        alignItems: "center",
        gap: GAP_SM,
        opacity: pressed ? 0.7 : 1,
        borderRadius: moderateScale(12, 0.5),
        paddingHorizontal: GAP_MD,
        paddingVertical: GAP_SM,
        alignSelf: "flex-start",
      })}
    >
      <AppIcon icon={RepeatIcon} size={13} color={colors.brand} />
      <Text style={{ color: colors.brand, fontSize: 12, fontWeight: "600" }}>
        Retry
      </Text>
    </Pressable>
  );
}

/**
 * Failure surface for an errored turn — mobile counterpart of web's
 * FailedResponse. The streamed text (if any) stays visible above; this strip
 * marks the answer as cut short and offers a retry.
 */
export function FailedResponse({
  error,
  hasPartialText,
  onRetry,
}: {
  error: string;
  hasPartialText: boolean;
  onRetry?: () => void;
}) {
  const { spacing, fontSize, moderateScale } = useResponsive();

  if (hasPartialText) {
    // Compact strip under the partial bubble — the answer was truncated.
    return (
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          gap: spacing.sm,
          marginTop: GAP_MD,
          paddingHorizontal: spacing.md,
        }}
      >
        <AppIcon icon={Alert01Icon} size={14} color={colors.zinc400} />
        <Text
          style={{
            color: colors.zinc400,
            fontSize: fontSize.xs,
            flexShrink: 1,
            marginRight: GAP_XS,
          }}
        >
          Response was cut short
        </Text>
        {onRetry ? <RetryButton onRetry={onRetry} /> : null}
      </View>
    );
  }

  // Full bubble — nothing streamed, so this IS the message.
  return (
    <View style={{ paddingHorizontal: spacing.md, width: "100%" }}>
      <View
        style={{
          alignSelf: "flex-start",
          maxWidth: "85%",
          backgroundColor: colors.zinc800,
          borderRadius: moderateScale(20, 0.5),
          padding: spacing.md,
          flexDirection: "row",
          alignItems: "flex-start",
          gap: spacing.sm,
        }}
      >
        <AppIcon
          icon={Alert01Icon}
          size={17}
          color={colors.zinc400}
          style={{ marginTop: 1 }}
        />
        <View style={{ flexShrink: 1, gap: GAP_SM }}>
          <Text style={{ color: colors.zinc200, fontSize: fontSize.base }}>
            This response failed
          </Text>
          <Text
            style={{ color: colors.zinc400, fontSize: fontSize.sm }}
            numberOfLines={2}
          >
            {error}
          </Text>
          {onRetry ? <RetryButton onRetry={onRetry} /> : null}
        </View>
      </View>
    </View>
  );
}
