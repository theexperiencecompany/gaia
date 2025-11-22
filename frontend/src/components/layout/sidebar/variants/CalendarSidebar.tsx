"use client";

import { Button } from "@heroui/button";
import { useRouter } from "next/navigation";

import { IntegrationConnectCard } from "@/components/shared/IntegrationConnectCard";
import Spinner from "@/components/ui/shadcn/spinner";
import CalendarSelector from "@/features/calendar/components/CalendarSelector";
import { useSharedCalendar } from "@/features/calendar/hooks/useSharedCalendar";
import { useIntegrations } from "@/features/integrations/hooks/useIntegrations";
import { CalendarAdd01Icon, GoogleCalendarIcon } from "@/icons";

export default function CalendarSidebar() {
  const router = useRouter();
  const { calendars, selectedCalendars, handleCalendarSelect, loading } =
    useSharedCalendar();
  const { getIntegrationStatus } = useIntegrations();

  const calendarStatus = getIntegrationStatus("google_calendar");
  const isCalendarConnected = calendarStatus?.connected || false;

  const handleCreateEvent = () => {
    // Navigate to calendar page which will trigger the event creation
    router.push("/calendar?create=true");
  };

  if (loading.calendars) {
    return (
      <div className="flex h-40 w-full flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }
  // Show connect button if calendar is not connected
  if (!isCalendarConnected) {
    return (
      <div className="flex flex-col gap-3">
        <IntegrationConnectCard
          icon={<GoogleCalendarIcon width={32} height={32} />}
          title="Connect Your Calendar"
          description="Manage events and view your schedule"
          buttonText="Connect Google Calendar"
          integrationId="google_calendar"
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <Button
        color="primary"
        size="sm"
        fullWidth
        onPress={handleCreateEvent}
        className="mb-4 flex justify-start text-sm font-medium text-primary"
        variant="flat"
      >
        <CalendarAdd01Icon width={18} height={18} />
        New Event
      </Button>

      <div>
        <div className="w-full px-2 pt-0 pb-1 text-xs font-medium text-foreground-400">
          Your Calendars
        </div>
        <CalendarSelector
          calendars={calendars}
          selectedCalendars={selectedCalendars}
          onCalendarSelect={handleCalendarSelect}
        />
      </div>
    </div>
  );
}
