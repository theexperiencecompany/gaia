import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useLoginModalActions } from "./useLoginModal";

export function useAuth() {
  const { email: userEmail } = useCurrentUser();
  const isAuthenticated = Boolean(userEmail);
  const { openModal: openLoginModal } = useLoginModalActions();

  return {
    userEmail,
    isAuthenticated,
    openLoginModal,
  };
}
