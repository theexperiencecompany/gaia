import { View } from "react-native";
import { type AnyIcon, AppIcon } from "@/components/icons";
import { Text } from "@/components/ui/text";

interface ToolCardHeaderProps {
  icon?: AnyIcon;
  iconColor?: string;
  title: string;
  subtitle?: string;
  count?: number;
  trailing?: React.ReactNode;
}

export function ToolCardHeader({
  icon,
  iconColor = "#00bbff",
  title,
  subtitle,
  count,
  trailing,
}: ToolCardHeaderProps) {
  return (
    <View className="flex-row items-center gap-3 mb-3">
      {icon && (
        <View className="w-8 h-8 rounded-full bg-zinc-800 items-center justify-center">
          <AppIcon icon={icon} size={16} color={iconColor} />
        </View>
      )}
      <View className="flex-1">
        <View className="flex-row items-center gap-2">
          <Text className="text-zinc-100 text-base font-semibold">{title}</Text>
          {count !== undefined && (
            <View className="px-2 py-0.5 rounded-full bg-zinc-800">
              <Text className="text-zinc-200 text-xs font-medium">{count}</Text>
            </View>
          )}
        </View>
        {subtitle && (
          <Text className="text-zinc-500 text-xs mt-0.5">{subtitle}</Text>
        )}
      </View>
      {trailing}
    </View>
  );
}
