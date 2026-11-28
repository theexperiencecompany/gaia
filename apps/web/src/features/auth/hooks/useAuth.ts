import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useLoginModalActions } from "./useLoginModal";

export function useAuth() {
  const userEmail = useCurrentUser()?.email;
  const isAuthenticated = Boolean(userEmail);
  const { openModal: openLoginModal } = useLoginModalActions();

  return {
    userEmail,
    isAuthenticated,
    openLoginModal,
  };
}
