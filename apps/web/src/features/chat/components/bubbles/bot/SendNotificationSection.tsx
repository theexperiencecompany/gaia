import { Chip } from "@heroui/chip";
import { CheckmarkCircle02Icon, NotificationIcon } from "@icons";
import { NOTIFICATION_PLATFORM_LABELS } from "@/features/notification/constants";
import type { SendNotificationData } from "@/types/features/notificationTypes";

const CHANNEL_LABELS: Record<string, string> = {
  ...NOTIFICATION_PLATFORM_LABELS,
  inapp: "In-app",
};

interface SendNotificationSectionProps {
  send_notification_data: SendNotificationData;
}

export default function SendNotificationSection({
  send_notification_data,
}: SendNotificationSectionProps) {
  const { title, message, delivered_channels } = send_notification_data;

  return (
    <div className="mt-3 w-full max-w-md rounded-2xl bg-zinc-800 p-4 text-white">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <NotificationIcon className="h-5 w-5 text-zinc-400" />
          <span className="text-sm font-medium">Notification sent</span>
        </div>
        <CheckmarkCircle02Icon className="h-5 w-5 text-emerald-400" />
      </div>

      <div className="rounded-2xl bg-zinc-900 p-3">
        <p className="text-sm font-medium text-zinc-100">{title}</p>
        <p className="mt-0.5 line-clamp-2 text-sm text-zinc-400">{message}</p>
      </div>

      {delivered_channels.length > 0 ? (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-zinc-500">Delivered to</span>
          {delivered_channels.map((channel) => (
            <Chip
              key={channel}
              size="sm"
              variant="flat"
              className="bg-zinc-700 text-zinc-300"
            >
              {CHANNEL_LABELS[channel] ?? channel}
            </Chip>
          ))}
        </div>
      ) : (
        <p className="mt-3 text-xs text-zinc-500">
          Queued — waiting for a channel to confirm delivery
        </p>
      )}
    </div>
  );
}
