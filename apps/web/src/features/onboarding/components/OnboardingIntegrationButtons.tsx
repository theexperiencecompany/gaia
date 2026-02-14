import { Button } from "@heroui/button";
import { Input } from "@heroui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { ScrollShadow } from "@heroui/scroll-shadow";
import { CancelIcon, ConnectIcon } from "@icons";
import type React from "react";
import { useState } from "react";
import { Gmail, GoogleCalendarIcon } from "@/components/shared/icons";
import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useFetchIntegrationStatus } from "@/features/integrations";
import { useIntegrationSearch } from "@/features/integrations/hooks/useIntegrationSearch";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { useIntegrationsStore } from "@/stores/integrationsStore";

interface OnboardingIntegrationButtonsProps {
  className?: string;
}

export const OnboardingIntegrationButtons: React.FC<
  OnboardingIntegrationButtonsProps
> = ({ className = "" }) => {
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);
  const { connectIntegration, getIntegrationStatus, integrations } =
    useIntegrations();
  useFetchIntegrationStatus({ refetchOnMount: "always" });

  const gmailStatus = getIntegrationStatus("gmail");
  const calendarStatus = getIntegrationStatus("googlecalendar");
  const isGmailConnected = gmailStatus?.connected || false;
  const isCalendarConnected = calendarStatus?.connected || false;

  const handleGmailConnect = async () => {
    try {
      await connectIntegration("gmail");
    } catch (error) {
      console.error("Failed to connect Gmail:", error);
    }
  };

  const handleCalendarConnect = async () => {
    try {
      await connectIntegration("googlecalendar");
    } catch (error) {
      console.error("Failed to connect Calendar:", error);
    }
  };

  const handleIntegrationConnect = async (integrationId: string) => {
    try {
      await connectIntegration(integrationId);
    } catch (error) {
      console.error(`Failed to connect ${integrationId}:`, error);
    }
  };

  const baseIntegrations = integrations.filter(
    (int) =>
      int.id !== "gmail" &&
      int.id !== "googlecalendar" &&
      int.available &&
      !int.isSpecial,
  );

  const { filteredIntegrations } = useIntegrationSearch(baseIntegrations);

  // Get search state from store
  const searchQuery = useIntegrationsStore((state) => state.searchQuery);
  const setSearchQuery = useIntegrationsStore((state) => state.setSearchQuery);
  const clearSearch = useIntegrationsStore((state) => state.clearSearch);

  return (
    <div className={`mt-3 ml-1 flex w-fit flex-col gap-2 ${className}`}>
      <div className="flex flex-row gap-2">
        <Button
          onPress={handleGmailConnect}
          disabled={isGmailConnected}
          variant="flat"
          color={isGmailConnected ? "success" : "default"}
          size="sm"
          startContent={<Gmail width={17} height={17} />}
        >
          {isGmailConnected ? "Gmail Connected" : "Connect Gmail"}
        </Button>

        <Button
          onPress={handleCalendarConnect}
          disabled={isCalendarConnected}
          variant="flat"
          color={isCalendarConnected ? "success" : "default"}
          size="sm"
          startContent={<GoogleCalendarIcon width={17} height={17} />}
        >
          {isCalendarConnected ? "Calendar Connected" : "Connect Calendar"}
        </Button>

        <Popover
          placement="bottom"
          isOpen={isPopoverOpen}
          backdrop="blur"
          onOpenChange={setIsPopoverOpen}
        >
          <PopoverTrigger>
            <Button
              variant="flat"
              size="sm"
              startContent={<ConnectIcon width={16} height={16} />}
            >
              Connect More Integrations
            </Button>
          </PopoverTrigger>

          <PopoverContent className="w-fit overflow-hidden rounded-2xl p-0 relative min-h-100 min-w-130 max-w-130 flex flex-col justify-start">
            <div className="flex w-full justify-between px-4 items-center gap-1">
              <div className="pt-4 pb-2 w-full gap-0.5">
                <p className="text-sm font-semibold">More Integrations</p>
                <p className="text-xs text-zinc-500">
                  Connect additional services
                </p>
              </div>

              <Input
                variant="flat"
                radius="full"
                size="sm"
                placeholder="Search..."
                value={searchQuery}
                isClearable
                onValueChange={setSearchQuery}
                onClear={clearSearch}
              />

              <Button
                type="button"
                isIconOnly
                variant="light"
                size="sm"
                onPress={() => setIsPopoverOpen(false)}
              >
                <CancelIcon className="text-zinc-300" width={15} height={15} />
              </Button>
            </div>

            <ScrollShadow className="max-h-80 w-full">
              <div className="py-2 pl-2">
                {filteredIntegrations.length === 0 ? (
                  <div className="px-4 py-8 text-center">
                    <p className="text-sm text-zinc-500">
                      No additional integrations available
                    </p>
                  </div>
                ) : (
                  filteredIntegrations.map((integration) => {
                    const status = getIntegrationStatus(integration.id);
                    const isConnected = status?.connected || false;

                    return (
                      <div
                        key={integration.id}
                        className="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-zinc-800/50"
                      >
                        <div className="flex min-w-0 flex-1 items-center gap-3">
                          <div className="shrink-0">
                            {getToolCategoryIcon(integration.id, {
                              size: 24,
                              width: 24,
                              height: 24,
                              showBackground: false,
                            })}
                          </div>

                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-medium">
                              {integration.name}
                            </p>
                            {integration.description && (
                              <p className="truncate text-xs text-zinc-500">
                                {integration.description}
                              </p>
                            )}
                          </div>
                        </div>

                        <Button
                          size="sm"
                          variant="flat"
                          color={isConnected ? "success" : "default"}
                          disabled={isConnected}
                          onPress={() =>
                            handleIntegrationConnect(integration.id)
                          }
                          className="shrink-0"
                        >
                          {isConnected ? "Connected" : "Connect"}
                        </Button>
                      </div>
                    );
                  })
                )}
              </div>
            </ScrollShadow>
          </PopoverContent>
        </Popover>
      </div>

      <p className="pl-1 text-xs text-zinc-500">
        You can always connect these later in settings
      </p>
    </div>
  );
};

export default OnboardingIntegrationButtons;
