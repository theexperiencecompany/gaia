"use client";

import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { usePathname } from "next/navigation";

import { handleAuthLogin } from "@/features/auth/hooks/handleAuthLogin";
import {
  useLoginModal,
  useLoginModalActions,
} from "@/features/auth/hooks/useLoginModal";
import { Login02Icon } from "@/icons";

import { Button } from "../../../components/ui/shadcn/button";
import { RaisedButton } from "@/components/ui";

export default function LoginModal() {
  const isOpen = useLoginModal();
  const { setLoginModalOpen } = useLoginModalActions();
  const pathname = usePathname();

  // Prevent rendering on /login or /signup pages
  if (pathname === "/login" || pathname === "/signup") return null;

  return (
    <Modal
      isOpen={isOpen}
      onOpenChange={(v) => setLoginModalOpen(v)}
      isDismissable={false}
      backdrop="blur"
      isKeyboardDismissDisabled
      hideCloseButton
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
