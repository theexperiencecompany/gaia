import type { ReactNode } from "react";

interface SettingsOptionProps {
  icon: ReactNode;
  title: string;
  description: string;
  action: ReactNode;
  className?: string;
}

export function SettingsOption({
  icon,
  title,
  description,
  action,
  className = "",
}: SettingsOptionProps) {
  return (
    <div
      className={`flex items-center justify-between ${className} mx-auto max-w-3xl`}
    >
      <div className="flex items-center space-x-3">
        <div className="flex items-center justify-center rounded-xl bg-zinc-800 p-2">
          {icon}
        </div>
        <div>
          <h3 className="text-base font-medium text-white">{title}</h3>
          <p className="text-xs text-zinc-500">{description}</p>
        </div>
      </div>
      {action}
    </div>
  );
}
