import type { ReactNode } from "react";
import PopupRouteLock from "@/features/desktop-popup/components/PopupRouteLock";
import ProvidersLayout from "@/layouts/ProvidersLayout";

/**
 * The assistant popup needs the full app provider stack (auth, query,
 * websocket, toasts) — the same one `(main)` mounts — without any of
 * its sidebar/header chrome. PopupRouteLock pins the windows to their
 * routes: shared chat components must never navigate the popup away.
 */
export default function DesktopPopupLayout({
  children,
}: {
  children: ReactNode;
}) {
  return (
    <ProvidersLayout>
      <PopupRouteLock />
      {children}
    </ProvidersLayout>
  );
}
