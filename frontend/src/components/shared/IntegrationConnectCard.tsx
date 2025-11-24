import { Button } from "@heroui/button";
import type React from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

interface IntegrationConnectCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  buttonText: string;
  integrationId: string;
  outlined?: boolean;
  small?: boolean;
}

export const IntegrationConnectCard: React.FC<IntegrationConnectCardProps> = ({
  icon,
  title,
  description,
  buttonText,
  integrationId,
  outlined = false,
  small = false,
}) => {
  const { connectIntegration } = useIntegrations();

  const handleConnect = async () => {
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error(`Failed to connect ${integrationId}:`, error);
    }
  };

  return (
    <div
      className={`flex flex-col items-center justify-center gap-1 ${outlined ? "rounded-3xl border border-dashed border-zinc-700 bg-zinc-800/50 p-4" : ""}`}
    >
      <div className="mb-2">{icon}</div>
      <div className="text-center">
        <p className={`${small && "text-sm"} font-medium text-foreground`}>
          {title}
        </p>
        <p
          className={`${small ? "text-xs" : "text-sm"} text-sm text-foreground-400`}
        >
          {description}
        </p>
      </div>
      <Button
        color="primary"
        onPress={handleConnect}
        size={small ? "sm" : "md"}
        className="mt-2 px-4"
      >
        {buttonText}
      </Button>
    </div>
  );
};
