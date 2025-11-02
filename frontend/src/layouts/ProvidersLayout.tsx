"use client";

import { ReactNode, Suspense } from "react";

import SuspenseLoader from "@/components/shared/SuspenseLoader";
import { Toaster } from "@/components/ui/shadcn/sonner";
import LoginModal from "@/features/auth/components/LoginModal";
import { useNotifications } from "@/features/notification/hooks/useNotifications";
import { useNotificationWebSocket } from "@/features/notification/hooks/useNotificationWebSocket";
import GlobalAuth from "@/hooks/providers/GlobalAuth";
import GlobalInterceptor from "@/hooks/providers/GlobalInterceptor";
import { HeroUIProvider } from "@/layouts/HeroUIProvider";
import QueryProvider from "@/layouts/QueryProvider";

export default function ProvidersLayout({ children }: { children: ReactNode }) {
  const { addNotification, updateNotification } = useNotifications({
    limit: 100,
  });

  useNotificationWebSocket({
    onNotification: addNotification,
    onUpdate: updateNotification,
  });

  return (
    <HeroUIProvider>
      <QueryProvider>
        <Suspense fallback={<SuspenseLoader />}>
          <GlobalAuth />
        </Suspense>
        <GlobalInterceptor />
        {/* <HydrationManager /> */}
        <LoginModal />
        <Toaster closeButton richColors position="top-right" theme="dark" />
        {children}
      </QueryProvider>
    </HeroUIProvider>
  );
}
