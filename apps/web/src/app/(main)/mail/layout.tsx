import type { ReactNode } from "react";

export default function MailLayout({ children }: { children: ReactNode }) {
  return <div className="h-screen px-5">{children}</div>;
}
