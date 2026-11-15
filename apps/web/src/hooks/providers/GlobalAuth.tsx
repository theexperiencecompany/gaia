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

const GlobalAuth = ({
  knownSessionOnly = false,
}: {
  /** Marketing pages: ask /me only for a browser that has signed in. */
  knownSessionOnly?: boolean;
}) => {
  useFetchUser({ knownSessionOnly });
  useCheckoutResume();
  return null;
};

export default GlobalAuth;
