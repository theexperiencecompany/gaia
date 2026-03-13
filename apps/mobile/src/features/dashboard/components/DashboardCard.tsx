import { Card, PressableFeedback } from "heroui-native";
import type { ReactNode } from "react";
import { View } from "react-native";
import type { AnyIcon } from "@/components/icons";
import { AppIcon, ArrowRight01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface DashboardCardProps {
  title: string;
  icon: AnyIcon;
  iconColor?: string;
  badge?: number;
  subtitle?: ReactNode;
  children?: ReactNode;
  onPress?: () => void;
}

export function DashboardCard({
  title,
  icon,
  iconColor = "#00bbff",
  badge,
  subtitle,
  children,
  onPress,
}: DashboardCardProps) {
  const { spacing, fontSize } = useResponsive();

  return (
    <PressableFeedback
      onPress={onPress}
      isDisabled={!onPress}
      style={{ marginBottom: spacing.md }}
    >
      <Card
        variant="secondary"
        style={{
          borderRadius: 16,
          borderWidth: 1,
          borderColor: "rgba(255,255,255,0.08)",
          overflow: "hidden",
          backgroundColor: "rgba(255,255,255,0.04)",
        }}
      >
        {/* Card header */}
        <Card.Header
          style={{
            flexDirection: "row",
            alignItems: "center",
            paddingHorizontal: spacing.md,
            paddingTop: spacing.md,
            paddingBottom: children ? spacing.sm : spacing.md,
            gap: spacing.sm,
          }}
        >
          <View
            style={{
              width: 32,
              height: 32,
              borderRadius: 10,
              backgroundColor: `${iconColor}1a`,
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <AppIcon icon={icon} size={18} color={iconColor} />
          </View>

          <View style={{ flex: 1 }}>
            <View
              style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
            >
              <Card.Title
                style={{
                  fontSize: fontSize.md,
                  fontWeight: "600",
                  color: "#f4f4f5",
                }}
              >
                {title}
              </Card.Title>
              {typeof badge === "number" && badge > 0 && (
                <View
                  style={{
                    backgroundColor: iconColor,
                    borderRadius: 999,
                    minWidth: 20,
                    height: 20,
                    alignItems: "center",
                    justifyContent: "center",
                    paddingHorizontal: 5,
                  }}
                >
                  <Text
                    style={{
                      fontSize: fontSize.xs - 1,
                      fontWeight: "700",
                      color: "#000",
                    }}
                  >
                    {badge > 99 ? "99+" : String(badge)}
                  </Text>
                </View>
              )}
            </View>
            {subtitle && (
              <View style={{ marginTop: 2 }}>
                {typeof subtitle === "string" ? (
                  <Card.Description
                    style={{ fontSize: fontSize.xs, color: "#71717a" }}
                  >
                    {subtitle}
                  </Card.Description>
                ) : (
                  subtitle
                )}
              </View>
            )}
          </View>

          {onPress && (
            <AppIcon
              icon={ArrowRight01Icon}
              size={16}
              color="rgba(255,255,255,0.25)"
            />
          )}
        </Card.Header>

        {/* Card content */}
        {children && (
          <Card.Body
            style={{
              borderTopWidth: 1,
              borderTopColor: "rgba(255,255,255,0.06)",
              padding: 0,
            }}
          >
            {children}
          </Card.Body>
        )}
      </Card>
    </PressableFeedback>
  );
}
