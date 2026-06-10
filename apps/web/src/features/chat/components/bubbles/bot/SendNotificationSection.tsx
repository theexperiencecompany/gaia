import { CheckmarkCircle02Icon, NotificationIcon } from "@icons";
import Image from "next/image";
import {
  NOTIFICATION_CHANNEL_ICONS,
  NOTIFICATION_CHANNEL_LABELS,
} from "@/features/notification/constants";
import type { SendNotificationData } from "@/types/features/notificationTypes";

interface SendNotificationSectionProps {
  send_notification_data: SendNotificationData;
}

export default function SendNotificationSection({
  send_notification_data,
}: SendNotificationSectionProps) {
  const { title, message, delivered_channels } = send_notification_data;
  const isDelivered = delivered_channels.length > 0;

  return (
    <div className="mt-3 w-full max-w-sm">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-emerald-400">
        <CheckmarkCircle02Icon className="size-4" />
        Notification sent
      </div>

      <div className="flex items-center gap-3 rounded-[22px] bg-zinc-800 p-3.5 shadow-2xl shadow-black/40">
        {isDelivered ? (
          <div className="flex shrink-0 -space-x-2">
            {delivered_channels.map((channel) => {
              const icon = NOTIFICATION_CHANNEL_ICONS[channel];
              const label = NOTIFICATION_CHANNEL_LABELS[channel] ?? channel;
              if (!icon) return null;
              return (
                <Image
                  key={channel}
                  src={icon}
                  alt={label}
                  title={label}
                  width={44}
                  height={44}
                  className="size-11 rounded-xl ring-2 ring-zinc-800"
                />
              );
            })}
          </div>
        ) : (
          <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-zinc-700">
            <NotificationIcon className="size-6 text-zinc-300" />
          </div>
        )}

        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-white">{title}</p>
          <p className="mt-0.5 line-clamp-2 text-[13px] leading-snug text-zinc-300">
            {message}
          </p>
          {!isDelivered && (
            <p className="mt-1 text-[11px] text-zinc-500">
              Queued — waiting for a channel to confirm delivery
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
