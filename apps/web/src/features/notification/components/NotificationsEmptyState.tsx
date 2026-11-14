import { NotificationIcon } from "@icons";

interface NotificationsEmptyStateProps {
  title: string;
  description: string;
}

export const NotificationsEmptyState = ({
  title,
  description,
}: NotificationsEmptyStateProps) => {
  return (
    <div className="flex flex-col items-center gap-3 text-center">
      <div className="flex size-12 items-center justify-center rounded-full bg-zinc-800/80">
        <NotificationIcon className="size-5 text-zinc-500" />
      </div>
      <div>
        <p className="text-sm font-medium text-zinc-200">{title}</p>
        <p className="mt-1 text-xs text-zinc-500">{description}</p>
      </div>
    </div>
  );
};
