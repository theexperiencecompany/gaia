"use client";

import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { usePathname } from "next/navigation";

import { RaisedButton } from "@/components/ui/raised-button";
import { handleAuthLogin } from "@/features/auth/hooks/handleAuthLogin";
import {
  useLoginModal,
  useLoginModalActions,
} from "@/features/auth/hooks/useLoginModal";
import { Login02Icon } from "@/icons";

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
  "/subscription",
  "/redirect",
  "/notifications",
  "/goals",
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

  if (pathname === "/login" || pathname === "/signup") return null;

  // Allow dismissing everywhere EXCEPT main app routes (which require auth)
  const canDismiss = !isNonDismissableRoute(pathname);

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
            onClick={handleAuthLogin}
          >
            <Login02Icon width={22} height={22} />
            Sign in
          </RaisedButton>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
