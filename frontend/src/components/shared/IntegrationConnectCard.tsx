import { Button } from "@heroui/button";
import React from "react";

import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

interface IntegrationConnectCardProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  buttonText: string;
  integrationId: string;
}

export const IntegrationConnectCard: React.FC<IntegrationConnectCardProps> = ({
  icon,
  title,
  description,
  buttonText,
  integrationId,
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
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-zinc-700 bg-zinc-900/50 p-6">
      <div className="opacity-50">{icon}</div>
      <div className="text-center">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="mt-1 text-xs text-foreground-400">{description}</p>
      </div>
      <Button
        color="primary"
        size="sm"
        fullWidth
        onPress={handleConnect}
        className="mt-2"
      >
        {buttonText}
      </Button>
    </div>
  );
};
