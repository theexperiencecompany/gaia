import type React from "react";

import { cn } from "@/lib/utils";

interface DateSeparatorProps {
  date: string;
  className?: string;
}

export const DateSeparator: React.FC<DateSeparatorProps> = ({
  date,
  className = "",
}) => {
  return (
    <div className={cn(`flex items-center justify-center py-4`, className)}>
      <div className="rounded-full bg-surface-950 px-4 py-1 dark:bg-surface-200">
        <span className="font-medium text-surface-400 dark:text-foreground-400">
          {date}
        </span>
      </div>
    </div>
  );
};
