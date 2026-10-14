"use client";

import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { Login02Icon } from "@icons";
import { useEffect, useState } from "react";
import { RaisedButton } from "@/components/ui/raised-button";
import { handleAuthLogin } from "@/features/auth/hooks/handleAuthLogin";
import {
  useLoginModal,
  useLoginModalActions,
} from "@/features/auth/hooks/useLoginModal";
import type { SetupStatus } from "@/features/settings/api/providersApi";
import { providersApi } from "@/features/settings/api/providersApi";
import { usePathname, useRouter } from "@/i18n/navigation";
import { track } from "@/lib/analytics";
import { isSelfhostWeb } from "@/lib/selfhost";

// Routes where login modal should NOT be dismissable (main app routes that require auth)
const NON_DISMISSABLE_ROUTE_PREFIXES = [
  "/c",
  "/mail",
  "/integrations",
  "/workflows",
  "/todos",
  "/onboarding",
  "/settings",
  "/pins",
  "/redirect",
  "/notifications",
  "/calendar",
  "/dashboard",
];

const isNonDismissableRoute = (pathname: string): boolean => {
  return NON_DISMISSABLE_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
};

export default function LoginModal() {
  const isOpen = useLoginModal();
  const { setLoginModalOpen } = useLoginModalActions();
  const pathname = usePathname();
  const router = useRouter();

  // Local auth has no WorkOS routes, so Sign in goes to /login. Plain state +
  // effect (mounted above QueryClientProvider), resolved once per session;
  // hosted GAIA is always WorkOS and has no setup surface to ask.
  const [authMode, setAuthMode] = useState<SetupStatus["auth_mode"] | null>(
    () => (isSelfhostWeb() ? null : "workos"),
  );

  useEffect(() => {
    if (!isOpen || authMode) return;
    let cancelled = false;
    providersApi
      .fetchSetupStatus()
      .then((status) => {
        if (!cancelled) setAuthMode(status.auth_mode);
      })
      .catch(() => {
        // Status unreachable → assume hosted so existing behavior holds.
        if (!cancelled) setAuthMode("workos");
      });
    return () => {
      cancelled = true;
    };
  }, [isOpen, authMode]);

  if (pathname === "/login" || pathname === "/signup") return null;

  // Allow dismissing everywhere EXCEPT main app routes (which require auth)
  const canDismiss = !isNonDismissableRoute(pathname);
  const isLocalAuth = authMode === "local";

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(v) => setLoginModalOpen(v)}
      isDismissable={canDismiss}
      backdrop="blur"
      className="outline-none"
      isKeyboardDismissDisabled={!canDismiss}
      hideCloseButton={!canDismiss}
    >
      <ModalContent className="p-4">
        <ModalBody>
          <div className="mb-3 space-y-3 text-center">
            <div className="text-5xl font-medium">Login</div>
            <div className="text-md text-foreground-600">
              Please login to continue your journey with GAIA.
            </div>
          </div>
          <RaisedButton
            color="#00bbff"
            className="text-md w-full text-primary-foreground!"
            onClick={() => {
              track("navigation:cta_clicked", {
                location: "login_modal",
                destination: isLocalAuth ? "/login" : "workos_oauth",
              });
              if (isLocalAuth) {
                setLoginModalOpen(false);
                router.push("/login");
              } else {
                handleAuthLogin();
              }
            }}
          >
            <Login02Icon width={22} height={22} />
            Sign in
          </RaisedButton>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
