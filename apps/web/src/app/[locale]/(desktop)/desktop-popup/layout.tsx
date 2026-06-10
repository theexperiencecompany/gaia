import type { ReactNode } from "react";
import ProvidersLayout from "@/layouts/ProvidersLayout";

/**
 * The assistant popup needs the full app provider stack (auth, query,
 * websocket, toasts) — the same one `(main)` mounts — without any of
 * its sidebar/header chrome.
 */
export default function DesktopPopupLayout({
  children,
}: {
  children: ReactNode;
}) {
  return <ProvidersLayout>{children}</ProvidersLayout>;
}
