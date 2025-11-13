import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { AlertCircleIcon } from "lucide-react";
import React from "react";

import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
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

  const content = (
    <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-4 text-white">
      <div className="flex flex-col gap-3">
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
              {isConnected ? (
                <Chip size="sm" variant="flat" color="success">
                  Connected
                </Chip>
              ) : (
                <Chip size="sm" variant="flat" color="warning">
                  Not Connected
                </Chip>
              )}
            </div>

            <p className="text-xs font-light text-zinc-400">
              {integration.description}
            </p>
          </div>
        </div>

        {!isConnected && (
          <div className="flex items-start gap-2 rounded-lg bg-warning-100/10 p-3">
            <AlertCircleIcon
              className="mt-0.5 flex-shrink-0 text-warning-500"
              size={16}
            />
            <p className="text-xs text-warning-700 dark:text-warning-400">
              {message}
            </p>
          </div>
        )}

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
    </div>
  );

  return (
    <CollapsibleListWrapper
      icon={getToolCategoryIcon(integration_id, {
        size: 20,
        width: 20,
        height: 20,
        showBackground: false,
      })}
      count={1}
      label="Integration Required"
      isCollapsible={true}
    >
      {content}
    </CollapsibleListWrapper>
  );
}
