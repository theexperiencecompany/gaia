import { Accordion, AccordionItem } from "@heroui/accordion";
import { Button } from "@heroui/button";
import { Chip } from "@heroui/chip";
import { Link } from "@heroui/link";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { Tooltip } from "@heroui/tooltip";
import { ArrowRight02Icon, ConnectIcon, InformationCircleIcon } from "@icons";
import { useRouter } from "next/navigation";
import { useState } from "react";
import CollapsibleListWrapper from "@/components/shared/CollapsibleListWrapper";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { integrationsApi, useIntegrations } from "@/features/integrations";
import type { SuggestedIntegration } from "@/features/integrations/types";
import { toast } from "@/lib/toast";

interface IntegrationListSectionProps {
  suggestedIntegrations?: SuggestedIntegration[];
}

interface AccordionTitleProps {
  title: string;
  count: number;
  tooltip: string;
}

function AccordionTitle({ title, count, tooltip }: AccordionTitleProps) {
  return (
    <div className="flex items-center gap-2">
      <span>{title}</span>
      <Chip
        size="sm"
        variant="flat"
        className="text-xs aspect-square flex items-center justify-center text-zinc-400"
      >
        {count}
      </Chip>
      <Tooltip content={tooltip} placement="top" className="ml-auto">
        <InformationCircleIcon
          width={18}
          height={18}
          className="text-zinc-500 cursor-help"
        >
          <title>Information</title>
        </InformationCircleIcon>
      </Tooltip>
    </div>
  );
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

  const handleSuggestedClick = (suggestion: SuggestedIntegration) => {
    router.push(`/marketplace/${encodeURIComponent(suggestion.slug)}`);
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
        onClick={() => handleSuggestedClick(suggestion)}
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

  const total_count = integrations.length;

  // Build accordion keys for sections that have items
  const defaultExpandedKeys = new Set<string>();
  if (connectedIntegrations.length > 0) defaultExpandedKeys.add("connected");
  if (suggestedIntegrations.length > 0) defaultExpandedKeys.add("suggested");
  if (notConnectedIntegrations.length > 0) defaultExpandedKeys.add("available");

  // Build accordion items array
  const accordionItems = [
    connectedIntegrations.length > 0 ? (
      <AccordionItem
        key="connected"
        aria-label="Connected"
        title={
          <AccordionTitle
            title="Connected"
            count={connectedIntegrations.length}
            tooltip="Your active integrations"
          />
        }
      >
        <ScrollShadow className="max-h-[150px]">
          {connectedIntegrations.map(renderIntegration)}
        </ScrollShadow>
      </AccordionItem>
    ) : null,
    suggestedIntegrations.length > 0 ? (
      <AccordionItem
        key="suggested"
        aria-label="Discover More"
        title={
          <AccordionTitle
            title="Discover More"
            count={suggestedIntegrations.length}
            tooltip="Public integrations from the community marketplace"
          />
        }
      >
        <ScrollShadow className="max-h-[150px] divide-y divide-zinc-700">
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
      </AccordionItem>
    ) : null,
    notConnectedIntegrations.length > 0 ? (
      <AccordionItem
        key="available"
        aria-label="Available"
        title={
          <AccordionTitle
            title="Available"
            count={notConnectedIntegrations.length}
            tooltip="Integrations provided natively by GAIA"
          />
        }
      >
        <ScrollShadow className="max-h-[200px]">
          {notConnectedIntegrations.map(renderIntegration)}
        </ScrollShadow>
      </AccordionItem>
    ) : null,
  ].filter(Boolean);

  const content = (
    <div className="w-full max-w-2xl rounded-3xl bg-zinc-800 p-4 text-white">
      <Accordion
        selectionMode="multiple"
        // showDivider={false}
        defaultExpandedKeys={defaultExpandedKeys}
        className="px-0"
        variant="light"
        isCompact
        itemClasses={{
          base: "py-0",
          title: "text-xs font-semibold text-zinc-400",
          trigger: "py-2 cursor-pointer",
          content: "pt-0 pb-4",
        }}
      >
        {accordionItems}
      </Accordion>
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
