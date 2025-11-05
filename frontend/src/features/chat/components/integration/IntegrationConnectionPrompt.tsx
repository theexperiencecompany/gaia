import { Button } from "@heroui/button";
import { Tooltip } from "@heroui/tooltip";
import { Settings } from "lucide-react";
import Link from "next/link";
import React, { useState } from "react";
import { toast } from "sonner";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { IntegrationConnectionData } from "@/types/features/integrationTypes";

interface IntegrationConnectionPromptProps {
  data: IntegrationConnectionData;
  onConnected?: () => void;
}

export const IntegrationConnectionPrompt: React.FC<
  IntegrationConnectionPromptProps
> = ({ data, onConnected }) => {
  const { connectIntegration, getIntegrationStatus } = useIntegrations();
  const [isConnecting, setIsConnecting] = useState(false);

  // Check if the integration is already connected
  const integrationStatus = getIntegrationStatus(data.integration_id);
  const isConnected = integrationStatus?.connected || false;

  const handleConnect = async () => {
    setIsConnecting(true);
    try {
      await connectIntegration(data.integration_id);
      toast.success(`${data.integration_name} connected successfully!`);
      onConnected?.();
    } catch (error) {
      console.error("Failed to connect integration:", error);
      toast.error(
        `Failed to connect ${data.integration_name}. Please try again.`,
      );
    } finally {
      setIsConnecting(false);
    }
  };

  return (
    <div className="w-full max-w-xl overflow-hidden rounded-3xl bg-zinc-800">
      {/* Header with integration icon and name */}
      <div className="flex items-center justify-between px-6 py-1">
        <div className="flex flex-row items-center gap-3 pt-3 pb-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-zinc-700">
            {getToolCategoryIcon(data.integration_id, {
              size: 20,
              width: 20,
              height: 20,
              showBackground: false,
              className: "h-5 w-5 object-contain",
            })}
          </div>
          <span className="text-sm font-medium">
            {isConnected ? "Already Connected" : "Connection Required"}
          </span>
        </div>
        <Tooltip content="Open Integration Settings">
          <Link href={data.settings_url}>
            <Button variant="flat" isIconOnly size="sm">
              <Settings className="h-4 w-4" />
            </Button>
          </Link>
        </Tooltip>
      </div>

      <div className="flex flex-col gap-1 px-6">
        <div className="text-sm leading-relaxed text-zinc-200">
          {data.message}
        </div>
      </div>

      {/* Action button */}
      <div className="flex justify-end px-6 pt-4 pb-5">
        <Button
          color={isConnected ? "success" : "primary"}
          onPress={isConnected ? undefined : handleConnect}
          isLoading={isConnecting}
          isDisabled={isConnected}
          size="sm"
          className="font-medium"
        >
          {isConnecting
            ? "Connecting..."
            : isConnected
              ? "Connected"
              : `Connect ${data.integration_name}`}
        </Button>
      </div>
    </div>
  );
};
