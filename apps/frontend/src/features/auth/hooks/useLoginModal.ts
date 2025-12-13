// src/hooks/useLoginModal.ts
import { useLoginModalStore } from "@/stores/loginModalStore";

export const useLoginModal = () => {
  return useLoginModalStore((state) => state.open);
};

export const useLoginModalActions = () => {
  const { setOpen, openModal, closeModal } = useLoginModalStore();

  return {
    setLoginModalOpen: setOpen,
    openModal,
    closeModal,
  };
};
