import { AlertCircleIcon, RepeatIcon } from "@icons";
import { Button, Card } from "heroui-native";
import { AppIcon } from "@/components/icons";

interface NetworkErrorStateProps {
  onRetry?: () => void;
  message?: string;
}

export function NetworkErrorState({
  onRetry,
  message = "Unable to connect to the server. Please check your connection and try again.",
}: NetworkErrorStateProps) {
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
            <AppIcon icon={AlertCircleIcon} size={32} color="#ef4444" />
          </Card.Body>
        </Card>

        <Card.Title className="text-center">Connection Error</Card.Title>

        <Card.Description className="text-center max-w-xs">
          {message}
        </Card.Description>

        {onRetry ? (
          <Button
            size="sm"
            variant="primary"
            onPress={onRetry}
            className="mt-2"
          >
            <AppIcon icon={RepeatIcon} size={16} color="#ffffff" />
            <Button.Label>Retry</Button.Label>
          </Button>
        ) : null}
      </Card.Body>
    </Card>
  );
}
