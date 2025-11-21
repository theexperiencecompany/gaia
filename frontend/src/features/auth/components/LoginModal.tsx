"use client";

import { Modal, ModalBody, ModalContent } from "@heroui/modal";
import { usePathname } from "next/navigation";

import { handleAuthLogin } from "@/features/auth/hooks/handleAuthLogin";
import {
  useLoginModal,
  useLoginModalActions,
} from "@/features/auth/hooks/useLoginModal";
import { UserIcon } from "@/icons";

import { Button } from "../../../components/ui/shadcn/button";

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
      isKeyboardDismissDisabled
      hideCloseButton
    >
      <ModalContent className="p-7">
        <ModalBody>
          <div className="mb-3 space-y-2 text-center">
            <div className="text-5xl font-medium">Login</div>
            <div className="text-md text-foreground-600">
              Please login to continue your journey with GAIA.
            </div>
          </div>
          <Button
            size="lg"
            className="text-md w-full gap-2 rounded-full bg-primary px-4 text-primary-foreground hover:bg-primary/90"
            onClick={handleAuthLogin}
          >
            <UserIcon size={18} />
            Sign in
          </Button>
        </ModalBody>
      </ModalContent>
    </Modal>
  );
}
