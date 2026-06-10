import { Button, Card } from "heroui-native";
import Animated, { FadeInUp } from "react-native-reanimated";
import type { AnyIcon } from "@/components/icons";
import { AppIcon } from "@/components/icons";

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
  iconColor = "#71717a",
  title,
  description,
  actionLabel,
  onAction,
}: EmptyStateProps) {
  return (
    <Animated.View
      entering={FadeInUp.duration(300).springify().damping(18)}
      style={{ flex: 1 }}
    >
      <Card
        variant="secondary"
        animation="disable-all"
        className="flex-1 items-center justify-center rounded-2xl px-5 py-16 mx-4"
      >
        <Card.Body className="items-center justify-center gap-3">
          <Card
            variant="secondary"
            animation="disable-all"
            className="w-[72px] h-[72px] rounded-full items-center justify-center mb-1"
          >
            <Card.Body className="items-center justify-center p-0">
              <AppIcon icon={icon} size={36} color={iconColor} />
            </Card.Body>
          </Card>

          <Card.Title className="text-center">{title}</Card.Title>

          {description ? (
            <Card.Description className="text-center max-w-[260px]">
              {description}
            </Card.Description>
          ) : null}

          {actionLabel && onAction ? (
            <Button
              size="sm"
              variant="secondary"
              onPress={onAction}
              className="mt-1"
            >
              <Button.Label>{actionLabel}</Button.Label>
            </Button>
          ) : null}
        </Card.Body>
      </Card>
    </Animated.View>
  );
}
