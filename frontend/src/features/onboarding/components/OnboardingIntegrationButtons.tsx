import { Button } from "@heroui/button";
import React from "react";

import { Gmail, GoogleCalendarIcon } from "@/components/shared/icons";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";

interface OnboardingIntegrationButtonsProps {
  className?: string;
}

export const OnboardingIntegrationButtons: React.FC<
  OnboardingIntegrationButtonsProps
> = ({ className = "" }) => {
  const { connectIntegration, getIntegrationStatus } = useIntegrations();

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

  return (
    <div className={`mt-3 ml-1 flex w-fit flex-col gap-2 ${className}`}>
      <div className="flex flex-row gap-2">
        <Button
          onPress={handleGmailConnect}
          disabled={isGmailConnected}
          variant="flat"
          size="sm"
          startContent={<Gmail width={17} height={17} />}
        >
          {isGmailConnected ? "Gmail Connected" : "Connect Gmail"}
        </Button>

        <Button
          onPress={handleCalendarConnect}
          disabled={isCalendarConnected}
          variant="flat"
          size="sm"
          startContent={<GoogleCalendarIcon width={17} height={17} />}
        >
          {isCalendarConnected ? "Calendar Connected" : "Connect Calendar"}
        </Button>
      </div>

      <p className="pl-1 text-xs text-zinc-500">
        You can always connect these later in settings
      </p>
    </div>
  );
};

export default OnboardingIntegrationButtons;
