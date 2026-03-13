import { GlobeIcon, RepeatIcon } from "@icons";
import { Button, Card } from "heroui-native";
import { AppIcon } from "@/components/icons";

interface OfflineStateProps {
  onRetry?: () => void;
}

export function OfflineState({ onRetry }: OfflineStateProps) {
  return (
    <Card
      variant="secondary"
      animation="disable-all"
      className="flex-1 items-center justify-center rounded-3xl p-6"
    >
      <Card.Body className="items-center justify-center gap-3">
        <Card
          variant="secondary"
          animation="disable-all"
          className="w-16 h-16 rounded-full items-center justify-center mb-1"
        >
          <Card.Body className="items-center justify-center p-0">
            <AppIcon icon={GlobeIcon} size={32} color="#6b7280" />
          </Card.Body>
        </Card>

        <Card.Title className="text-center">You're Offline</Card.Title>

        <Card.Description className="text-center max-w-xs">
          No internet connection detected. Please check your network settings
          and try again.
        </Card.Description>

        {onRetry ? (
          <Button
            size="sm"
            variant="primary"
            onPress={onRetry}
            className="mt-2"
          >
            <AppIcon icon={RepeatIcon} size={16} color="#ffffff" />
            <Button.Label>Try Again</Button.Label>
          </Button>
        ) : null}
      </Card.Body>
    </Card>
  );
}
