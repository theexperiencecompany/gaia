import { Button } from "@heroui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@heroui/popover";
import { ScrollShadow } from "@heroui/scroll-shadow";
import React, { useState } from "react";

import { getToolCategoryIcon } from "@/features/chat/utils/toolIcons";
import { useFetchIntegrationStatus } from "@/features/integrations";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { ConnectIcon, Gmail, GoogleCalendarIcon } from "@/icons";

interface OnboardingIntegrationButtonsProps {
  className?: string;
}

export const OnboardingIntegrationButtons: React.FC<
  OnboardingIntegrationButtonsProps
> = ({ className = "" }) => {
  // Force refetch on mount to show updated status after OAuth
  useFetchIntegrationStatus({ refetchOnMount: "always" });

  const { connectIntegration, getIntegrationStatus, integrations } =
    useIntegrations();
  const [isPopoverOpen, setIsPopoverOpen] = useState(false);

  // Check integration statuses
  const gmailStatus = getIntegrationStatus("gmail");
  const calendarStatus = getIntegrationStatus("google_calendar");
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
      await connectIntegration("google_calendar");
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

  // Filter out Gmail and Google Calendar from the list, and only show available integrations
  const otherIntegrations = integrations.filter(
    (int) =>
      int.id !== "gmail" &&
      int.id !== "google_calendar" &&
      int.loginEndpoint && // Only show integrations that can be connected
      !int.isSpecial, // Exclude special/unified integrations
  );

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
          <PopoverContent className="w-fit overflow-hidden rounded-2xl p-0">
            <div className="pt-4 pb-2">
              <p className="text-center text-sm font-semibold">
                More Integrations
              </p>
              <p className="mt-0.5 text-center text-xs text-zinc-500">
                Connect additional services
              </p>
            </div>
            <ScrollShadow className="max-h-80">
              <div className="py-2 pl-2">
                {otherIntegrations.length === 0 ? (
                  <div className="px-4 py-8 text-center">
                    <p className="text-sm text-zinc-500">
                      No additional integrations available
                    </p>
                  </div>
                ) : (
                  otherIntegrations.map((integration) => {
                    const status = getIntegrationStatus(integration.id);
                    const isConnected = status?.connected || false;

                    return (
                      <div
                        key={integration.id}
                        className="flex w-full max-w-xl items-center justify-between gap-3 rounded-lg px-3 py-2.5 transition-colors hover:bg-zinc-800/50"
                      >
                        <div className="flex min-w-0 flex-1 items-center gap-3">
                          <div className="flex-shrink-0">
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
                          className="flex-shrink-0"
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
