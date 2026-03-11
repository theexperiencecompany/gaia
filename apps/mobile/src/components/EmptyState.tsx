import { Pressable, View } from "react-native";
import type { AnyIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface EmptyStateProps {
  icon: AnyIcon;
  iconColor?: string;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  icon,
  iconColor = "#3f3f46",
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  const { spacing, fontSize } = useResponsive();

  return (
    <View
      style={{
        flex: 1,
        alignItems: "center",
        justifyContent: "center",
        paddingHorizontal: spacing.xl,
        paddingVertical: spacing.xl * 2,
        gap: spacing.md,
      }}
    >
      <View
        style={{
          width: 72,
          height: 72,
          borderRadius: 36,
          backgroundColor: "rgba(255,255,255,0.04)",
          borderWidth: 1,
          borderColor: "rgba(255,255,255,0.06)",
          alignItems: "center",
          justifyContent: "center",
          marginBottom: spacing.xs,
        }}
      >
        <AppIcon icon={icon} size={36} color={iconColor} />
      </View>

      <View style={{ alignItems: "center", gap: 6 }}>
        <Text
          style={{
            fontSize: fontSize.base,
            fontWeight: "600",
            color: "#d4d4d8",
            textAlign: "center",
          }}
        >
          {title}
        </Text>
        {description ? (
          <Text
            style={{
              fontSize: fontSize.sm,
              color: "#71717a",
              textAlign: "center",
              maxWidth: 260,
              lineHeight: fontSize.sm * 1.5,
            }}
          >
            {description}
          </Text>
        ) : null}
      </View>

      {actionLabel && onAction ? (
        <Pressable
          onPress={onAction}
          style={({ pressed }) => ({
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingVertical: spacing.sm,
            borderRadius: 10,
            backgroundColor: pressed
              ? "rgba(22,193,255,0.18)"
              : "rgba(22,193,255,0.12)",
            borderWidth: 1,
            borderColor: "rgba(22,193,255,0.2)",
            marginTop: spacing.xs,
          })}
        >
          <Text
            style={{
              fontSize: fontSize.sm,
              fontWeight: "600",
              color: "#16c1ff",
            }}
          >
            {actionLabel}
          </Text>
        </Pressable>
      ) : null}
    </View>
  );
}
