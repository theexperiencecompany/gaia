import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { AlertCircleIcon } from "lucide-react";
import React from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations";
import { IntegrationConnectionData } from "@/types/features/integrationTypes";

interface IntegrationConnectionPromptProps {
  integration_connection_required: Pick<
    IntegrationConnectionData,
    "integration_id" | "message"
  >;
}

export default function IntegrationConnectionPrompt({
  integration_connection_required,
}: IntegrationConnectionPromptProps) {
  const { integration_id, message } = integration_connection_required;
  const { integrations, connectIntegration } = useIntegrations();

  const integration = integrations.find((i) => i.id === integration_id);

  if (!integration) {
    return null;
  }

  const isConnected = integration.status === "connected";
  const isAvailable = !!integration.loginEndpoint;

  const handleConnect = async () => {
    try {
      await connectIntegration(integration.id);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  return (
    <div className="mb-3 flex flex-col gap-3 overflow-hidden rounded-2xl border border-warning-500/20 bg-warning-50/5 p-4">
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 pt-0.5">
          {getToolCategoryIcon(integration_id, {
            size: 22,
            width: 22,
            height: 22,
            showBackground: false,
          })}
        </div>

        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">{integration.name}</span>
            <Chip size="sm" variant="flat" color="warning">
              Not Connected
            </Chip>
          </div>

          <p className="text-xs font-light text-zinc-400">
            {integration.description}
          </p>
        </div>
      </div>

      <div className="flex items-start gap-2 rounded-lg bg-warning-100/10 p-3">
        <AlertCircleIcon
          className="mt-0.5 flex-shrink-0 text-warning-500"
          size={16}
        />
        <p className="text-xs text-warning-700 dark:text-warning-400">
          {message}
        </p>
      </div>

      <div className="flex gap-2">
        {isAvailable && !isConnected && (
          <Button
            size="sm"
            variant="flat"
            color="primary"
            className="text-xs"
            onPress={handleConnect}
          >
            Connect
          </Button>
        )}
      </div>
    </div>
  );
}
