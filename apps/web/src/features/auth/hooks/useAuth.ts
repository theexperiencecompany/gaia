import { useCurrentUser } from "@/features/auth/hooks/useCurrentUser";
import { useLoginModalActions } from "./useLoginModal";

/**
 * Custom hook for authentication state and actions.
 *
 * Provides:
 * - userEmail: Current user's email from store
 * - isAuthenticated: Boolean indicating if user is logged in
 * - openLoginModal: Function to open the login modal
 *
 * @example
 * ```tsx
 * const { isAuthenticated, openLoginModal } = useAuth();
 *
 * if (!isAuthenticated) {
 *   openLoginModal();
 *   return;
 * }
 * ```
 */
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
