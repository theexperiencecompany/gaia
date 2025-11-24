import type { ReactNode } from "react";

interface SettingsCardSimpleProps {
  children: ReactNode;
  className?: string;
}

export function SettingsCardSimple({
  children,
  className = "",
}: SettingsCardSimpleProps) {
  return (
    <div
      className={`mx-auto max-w-3xl rounded-2xl bg-[#141414] p-4 ${className}`}
    >
      {children}
    </div>
  );
}
