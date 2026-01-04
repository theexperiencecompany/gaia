import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { ScrollShadow } from "@heroui/scroll-shadow";

import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { ConnectIcon } from "@/components/shared/icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useIntegrations } from "@/features/integrations";

function IntegrationListSection() {
  const { integrations, connectIntegration } = useIntegrations();

  // Separate connected and not connected integrations
  const connectedIntegrations = integrations.filter(
    (i) => i.status === "connected",
  );
  const notConnectedIntegrations = integrations.filter(
    (i) => i.status !== "connected",
  );

  const total_count = integrations.length;
  const connected_count = connectedIntegrations.length;

  const handleConnect = async (integrationId: string) => {
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  const renderIntegration = (integration: (typeof integrations)[0]) => {
    const isConnected = integration.status === "connected";
    // Use backend's 'available' field - MCP integrations have available=true but loginEndpoint=null
    const isAvailable = integration.available ?? !!integration.loginEndpoint;

    return (
      <div
        key={integration.id}
        className="group flex items-start gap-3 p-3 transition-colors hover:bg-zinc-700"
      >
        <div className="flex-shrink-0 pt-0.5">
          {getToolCategoryIcon(integration.id, {
            size: 20,
            width: 20,
            height: 20,
            showBackground: false,
          })}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white">
              {integration.name}
            </span>
            {isConnected && (
              <Chip size="sm" variant="flat" color="success">
                Connected
              </Chip>
            )}
          </div>
          <p className="mt-1 text-xs text-zinc-400">
            {integration.description}
          </p>
        </div>

        {/* Show connect button for all available integrations */}
        {!isConnected && isAvailable && (
          <Button
            size="sm"
            variant="flat"
            color="primary"
            className="flex-shrink-0 text-xs"
            onPress={() => handleConnect(integration.id)}
          >
            Connect
          </Button>
        )}
      </div>
    );
  };

  const content = (
    <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-4 text-white">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-300">
          {connected_count} of {total_count} connected
        </span>
      </div>

      <div className="space-y-4">
        {/* Connected Integrations Section */}
        {connectedIntegrations.length > 0 && (
          <div>
            <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
              Connected ({connectedIntegrations.length})
            </h3>
            <ScrollShadow className="max-h-[200px] divide-y divide-zinc-700">
              {connectedIntegrations.map(renderIntegration)}
            </ScrollShadow>
          </div>
        )}

        {/* Not Connected Integrations Section */}
        {notConnectedIntegrations.length > 0 && (
          <div>
            <h3 className="mb-2 text-xs font-semibold tracking-wider text-zinc-400 uppercase">
              Available ({notConnectedIntegrations.length})
            </h3>
            <ScrollShadow className="max-h-[300px] divide-y divide-zinc-700">
              {notConnectedIntegrations.map(renderIntegration)}
            </ScrollShadow>
          </div>
        )}
      </div>
    </div>
  );

  return (
    <CollapsibleListWrapper
      icon={<ConnectIcon size={20} />}
      count={total_count}
      label="Integration"
      isCollapsible={true}
    >
      {content}
    </CollapsibleListWrapper>
  );
}

export { IntegrationListSection };
