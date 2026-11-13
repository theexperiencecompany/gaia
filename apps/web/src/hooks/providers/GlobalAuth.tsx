"use client";
/**
 * Isolates `useFetchUser` (which uses `useSearchParams()`) in its own
 * component so the parent (`ProvidersLayout`) can wrap it in a `<Suspense>`
 * boundary — otherwise Next.js throws "useSearchParams() should be wrapped in
 * a suspense boundary" during build/SSR (CSR bailout).
 */
// This GlobalAuth file is required because it requires the ReduxProvider wrapped around it

import useFetchUser from "@/features/auth/hooks/useFetchUser";
import { useCheckoutResume } from "@/features/pricing/hooks/useCheckoutResume";

const GlobalAuth = () => {
  useFetchUser();
  useCheckoutResume();
  return null;
};

export default GlobalAuth;
