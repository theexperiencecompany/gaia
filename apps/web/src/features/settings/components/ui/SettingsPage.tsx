import type { ReactNode } from "react";

interface SettingsPageProps {
  children: ReactNode;
}

export function SettingsPage({ children }: SettingsPageProps) {
  return <div className="mx-auto max-w-2xl space-y-6">{children}</div>;
}
