import { cn } from "@/lib";
import { ReactNode } from "react";

interface SettingsCardProps {
  icon?: ReactNode;
  title?: string;
  children: ReactNode;
  className?: string;
}

export function SettingsCard({
  icon,
  title,
  children,
  className = "",
}: SettingsCardProps) {
  return (
    <div
      className={`rounded-2xl bg-zinc-900 p-4 outline-1 outline-zinc-800 ${cn(className)}`}
    >
      {(icon || title) && (
        <div className="mb-1 flex items-center space-x-2">
          {icon && (
            <div className="flex h-6 w-6 items-center justify-center">
              {icon}
            </div>
          )}
          {title && (
            <div>
              <h3 className="text-base font-medium text-white">{title}</h3>
            </div>
          )}
        </div>
      )}
      {children}
    </div>
  );
}
