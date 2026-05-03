import type React from "react";
import { Pressable, Switch, View } from "react-native";
import type { AnyIcon } from "@/components/icons";
import { AppIcon, ArrowRight01Icon } from "@/components/icons";
import { Text } from "@/components/ui/text";
import { useResponsive } from "@/lib/responsive";

interface SettingsGroupProps {
  label?: string;
  children: React.ReactNode;
}

export function SettingsGroup({ label, children }: SettingsGroupProps) {
  const { spacing, fontSize } = useResponsive();

  return (
    <View style={{ gap: 0 }}>
      {label ? (
        <Text
          style={{
            fontSize: fontSize.xs,
            color: "#71717a",
            textTransform: "uppercase",
            letterSpacing: 0.8,
            marginBottom: spacing.xs,
            paddingHorizontal: spacing.xs,
          }}
        >
          {label}
        </Text>
      ) : null}
      <View
        style={{
          backgroundColor: "#18181b",
          borderRadius: 16,
          overflow: "hidden",
        }}
      >
        {children}
      </View>
    </View>
  );
}

interface SettingsRowProps {
  icon?: AnyIcon;
  iconColor?: string;
  iconBg?: string;
  title: string;
  subtitle?: string;
  rightElement?: React.ReactNode;
  showChevron?: boolean;
  onPress?: () => void;
  isDestructive?: boolean;
  isLast?: boolean;
}

export function SettingsRow({
  icon,
  iconColor = "#ffffff",
  iconBg = "rgba(255,255,255,0.06)",
  title,
  subtitle,
  rightElement,
  showChevron = false,
  onPress,
  isDestructive = false,
  isLast = false,
}: SettingsRowProps) {
  const { spacing, fontSize } = useResponsive();
  const titleColor = isDestructive ? "#ef4444" : "#ffffff";

  const titleLineHeight = Math.round(fontSize.md * 1.35);
  const subtitleLineHeight = Math.round(fontSize.xs * 1.4);

  const content = (
    <View>
      <View
        style={{
          flexDirection: "row",
          alignItems: "center",
          paddingHorizontal: spacing.md,
          paddingVertical: subtitle ? 12 : 14,
          gap: spacing.sm + 2,
          minHeight: 56,
        }}
      >
        {icon ? (
          <View
            style={{
              width: 28,
              height: 28,
              borderRadius: 8,
              backgroundColor: isDestructive ? "rgba(239,68,68,0.15)" : iconBg,
              alignItems: "center",
              justifyContent: "center",
              flexShrink: 0,
            }}
          >
            <AppIcon
              icon={icon}
              size={16}
              color={isDestructive ? "#ef4444" : iconColor}
            />
          </View>
        ) : null}

        <View style={{ flex: 1, minWidth: 0, justifyContent: "center" }}>
          <Text
            style={{
              fontSize: fontSize.md,
              fontWeight: "500",
              lineHeight: titleLineHeight,
              color: titleColor,
            }}
            numberOfLines={1}
          >
            {title}
          </Text>
          {subtitle ? (
            <Text
              style={{
                fontSize: fontSize.xs,
                lineHeight: subtitleLineHeight,
                color: "#71717a",
                marginTop: 2,
              }}
              numberOfLines={2}
            >
              {subtitle}
            </Text>
          ) : null}
        </View>

        {rightElement ? (
          <View style={{ flexShrink: 0 }}>{rightElement}</View>
        ) : null}

        {showChevron ? (
          <AppIcon icon={ArrowRight01Icon} size={16} color="#52525b" />
        ) : null}
      </View>

      {!isLast ? (
        <View
          style={{
            height: 1,
            backgroundColor: "rgba(255,255,255,0.06)",
            marginLeft: icon ? spacing.md + 28 + spacing.sm + 2 : spacing.md,
          }}
        />
      ) : null}
    </View>
  );

  if (onPress) {
    return (
      <Pressable
        onPress={onPress}
        style={({ pressed }) =>
          pressed ? { backgroundColor: "rgba(255,255,255,0.04)" } : {}
        }
      >
        {content}
      </Pressable>
    );
  }

  return content;
}

interface SettingsSwitchRowProps {
  icon?: AnyIcon;
  iconColor?: string;
  iconBg?: string;
  title: string;
  subtitle?: string;
  value: boolean;
  onValueChange: (value: boolean) => void;
  disabled?: boolean;
  isLast?: boolean;
}

export function SettingsSwitchRow({
  icon,
  iconColor = "#ffffff",
  iconBg = "rgba(255,255,255,0.06)",
  title,
  subtitle,
  value,
  onValueChange,
  disabled = false,
  isLast = false,
}: SettingsSwitchRowProps) {
  return (
    <SettingsRow
      icon={icon}
      iconColor={iconColor}
      iconBg={iconBg}
      title={title}
      subtitle={subtitle}
      isLast={isLast}
      rightElement={
        <Switch
          value={value}
          onValueChange={onValueChange}
          disabled={disabled}
          trackColor={{ false: "#3a3a3c", true: "rgba(22,193,255,0.6)" }}
          thumbColor={value ? "#16c1ff" : "#71717a"}
        />
      }
    />
  );
}
