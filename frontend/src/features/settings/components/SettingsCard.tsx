import { ReactNode } from "react";

import { cn } from "@/lib";

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
      className={`mx-auto max-w-3xl rounded-2xl bg-[#141414] p-4 ${cn(className)}`}
    >
      {(icon || title) && (
        <div className="mb-3 flex items-center space-x-1 text-zinc-400">
          {icon && (
            <div className="flex h-5 w-5 items-center justify-center">
              {icon}
            </div>
          )}
          {title && (
            <div>
              <h3 className="text-base font-normal">{title}</h3>
            </div>
          )}
        </div>
      )}
      {children}
    </div>
  );
}
