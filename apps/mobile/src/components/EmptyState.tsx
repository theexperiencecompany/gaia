import { Button } from "heroui-native";
import { View } from "react-native";
import { Text } from "@/components/ui/text";

interface EmptyStateProps {
  icon: string;
  title: string;
  description?: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function EmptyState({
  icon,
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <View className="flex-1 items-center justify-center px-8 py-16">
      <Text className="text-5xl mb-4">{icon}</Text>
      <Text className="text-lg font-semibold text-center mb-2">{title}</Text>
      {description && (
        <Text className="text-sm text-muted text-center mb-6">
          {description}
        </Text>
      )}
      {actionLabel && onAction && (
        <Button
          variant="secondary"
          size="sm"
          onPress={onAction}
          className="mt-2"
        >
          <Button.Label>{actionLabel}</Button.Label>
        </Button>
      )}
    </View>
  );
}
