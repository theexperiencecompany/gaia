import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Link } from "@heroui/link";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Tooltip } from "@heroui/tooltip";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import {
  ArrowRight02Icon,
  ConnectIcon,
  InformationCircleIcon,
} from "@/components/shared/icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { integrationsApi, useIntegrations } from "@/features/integrations";
import type { SuggestedIntegration } from "@/features/integrations/types";

interface IntegrationListSectionProps {
  suggestedIntegrations?: SuggestedIntegration[];
}

function IntegrationListSection({
  suggestedIntegrations = [],
}: IntegrationListSectionProps) {
  const router = useRouter();
  const { integrations, connectIntegration, refetch } = useIntegrations();
  const [connectingIds, setConnectingIds] = useState<Set<string>>(new Set());

  // Separate connected and not connected integrations, sorted alphabetically
  const connectedIntegrations = integrations
    .filter((i) => i.status === "connected")
    .sort((a, b) => a.name.localeCompare(b.name));
  const notConnectedIntegrations = integrations
    .filter((i) => i.status !== "connected")
    .sort((a, b) => a.name.localeCompare(b.name));

  const total_count = integrations.length;

  const handleConnect = async (integrationId: string, e: React.MouseEvent) => {
    e.stopPropagation(); // Prevent card click
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error("Failed to connect integration:", error);
    }
  };

  const handleConnectSuggested = async (
    suggestion: SuggestedIntegration,
    e: React.MouseEvent,
  ) => {
    e.stopPropagation(); // Prevent card click
    setConnectingIds((prev) => new Set(prev).add(suggestion.id));
    const toastId = toast.loading(`Adding ${suggestion.name}...`);

    try {
      const result = await integrationsApi.addIntegration(suggestion.id);

      if (result.status === "connected") {
        toast.success(`${suggestion.name} connected successfully`, {
          id: toastId,
        });
        await refetch();
      } else if (result.status === "redirect" && result.redirectUrl) {
        toast.dismiss(toastId);
        window.location.href = result.redirectUrl;
      } else {
        toast.error(`Failed to connect ${suggestion.name}`, { id: toastId });
      }
    } catch (error) {
      toast.error(
        `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
        { id: toastId },
      );
    } finally {
      setConnectingIds((prev) => {
        const next = new Set(prev);
        next.delete(suggestion.id);
        return next;
      });
    }
  };

  const handleIntegrationClick = (integrationId: string) => {
    router.push(`/integrations?id=${encodeURIComponent(integrationId)}`);
  };

  const handleSuggestedClick = (suggestionId: string) => {
    router.push(`/marketplace?id=${encodeURIComponent(suggestionId)}`);
  };

  const renderIntegration = (integration: (typeof integrations)[0]) => {
    const isConnected = integration.status === "connected";
    // Use backend's 'available' field for platform integrations
    const isAvailable =
      integration.source === "custom" || integration.available;

    return (
      <div
        key={integration.id}
        className="group flex items-start gap-3 p-3 transition-colors hover:bg-zinc-700 cursor-pointer"
        onClick={() => handleIntegrationClick(integration.id)}
      >
        <div className="shrink-0 pt-0.5">
          {getToolCategoryIcon(
            integration.id,
            {
              size: 20,
              width: 20,
              height: 20,
              showBackground: false,
            },
            integration.iconUrl,
          )}
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
            className="shrink-0 text-xs"
            onPress={(e) =>
              handleConnect(integration.id, e as unknown as React.MouseEvent)
            }
          >
            Connect
          </Button>
        )}
      </div>
    );
  };

  const renderSuggested = (suggestion: SuggestedIntegration) => {
    const isConnecting = connectingIds.has(suggestion.id);

    return (
      <div
        key={suggestion.id}
        className="group flex items-start gap-3 p-3 transition-colors hover:bg-zinc-700 cursor-pointer"
        onClick={() => handleSuggestedClick(suggestion.id)}
      >
        <div className="shrink-0 pt-0.5">
          {getToolCategoryIcon(
            suggestion.id,
            {
              size: 20,
              width: 20,
              height: 20,
              showBackground: false,
            },
            suggestion.iconUrl,
          )}
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-white">
              {suggestion.name}
            </span>
            <Chip size="sm" variant="flat" color="secondary">
              Community
            </Chip>
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-zinc-400">
            {suggestion.description}
          </p>
        </div>

        <Button
          size="sm"
          variant="flat"
          color="primary"
          className="shrink-0 text-xs"
          isLoading={isConnecting}
          onPress={(e) =>
            handleConnectSuggested(suggestion, e as unknown as React.MouseEvent)
          }
        >
          {isConnecting ? "Adding..." : "Add"}
        </Button>
      </div>
    );
  };

  const SectionHeader = ({
    title,
    count,
    tooltip,
  }: {
    title: string;
    count: number;
    tooltip: string;
  }) => (
    <div className="mb-2 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <h3 className="text-xs font-semibold text-zinc-400 uppercase">
          {title}
        </h3>
        <Tooltip content={tooltip} placement="top">
          <InformationCircleIcon className="h-3.5 w-3.5 text-zinc-500 cursor-help">
            <title>Information</title>
          </InformationCircleIcon>
        </Tooltip>
      </div>
      <Chip size="sm" variant="flat" className="text-xs">
        {count}
      </Chip>
    </div>
  );

  const content = (
    <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-4 text-white">
      <div className="space-y-6">
        {/* Connected Section */}
        {connectedIntegrations.length > 0 && (
          <div>
            <SectionHeader
              title="Connected"
              count={connectedIntegrations.length}
              tooltip="Your active integrations"
            />
            <ScrollShadow className="max-h-[200px] divide-y divide-zinc-700">
              {connectedIntegrations.map(renderIntegration)}
            </ScrollShadow>
          </div>
        )}

        {/* Discover More Section - Moved above Available */}
        {suggestedIntegrations.length > 0 && (
          <div>
            <SectionHeader
              title="Discover More"
              count={suggestedIntegrations.length}
              tooltip="Public integrations from the community marketplace"
            />
            <ScrollShadow className="max-h-[250px] divide-y divide-zinc-700">
              {suggestedIntegrations.map(renderSuggested)}
            </ScrollShadow>
            <div className="mt-3 flex justify-center">
              <Link
                href="/marketplace"
                className="text-xs text-primary hover:underline gap-1"
              >
                <span>Go to Marketplace</span>

                <ArrowRight02Icon width={16} height={16} />
              </Link>
            </div>
          </div>
        )}

        {/* Available Section */}
        {notConnectedIntegrations.length > 0 && (
          <div>
            <SectionHeader
              title="Available"
              count={notConnectedIntegrations.length}
              tooltip="Integrations provided natively by GAIA"
            />
            <ScrollShadow className="max-h-[200px] divide-y divide-zinc-700">
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
