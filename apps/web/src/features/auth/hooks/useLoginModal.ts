// src/hooks/useLoginModal.ts
import { useLoginModalStore } from "@/stores/loginModalStore";

export const useLoginModal = () => {
  return useLoginModalStore((state) => state.open);
};

export const useLoginModalActions = () => {
  const { setOpen, openModal, closeModal, suppressModal, unsuppressModal } =
    useLoginModalStore();

  return {
    setLoginModalOpen: setOpen,
    openModal,
    closeModal,
    /** Suppress/unsuppress the modal for surfaces with their own sign-in
     * affordance (desktop popup, setup wizard's account step). */
    suppressModal,
    unsuppressModal,
  };
};
