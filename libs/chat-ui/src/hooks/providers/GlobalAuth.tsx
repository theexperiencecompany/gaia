"use client";
/**
 * GlobalAuth Component
 *
 * This component is required to fix Next.js CSR bailout errors with useSearchParams().
 *
 * Problem:
 * The useFetchUser hook uses useSearchParams() from next/navigation, which can cause
 * "useSearchParams() should be wrapped in a suspense boundary" errors during build/SSR.
 * This happens because:
 * 1. useSearchParams() can trigger client-side rendering (CSR bailout)
 * 2. When components using it are rendered on the server during build, Next.js throws errors
 * 3. The hook needs to be isolated in a component that can be wrapped with Suspense
 *
 * Solution:
 * By isolating useFetchUser() in this separate component, we can:
 * 1. Wrap it with <Suspense> boundary in the parent component
 * 2. Prevent the CSR bailout from affecting other parts of the app
 * 3. Allow the auth logic to work properly while avoiding build errors
 *
 * This component must be wrapped with Suspense in the parent ProvidersLayout.
 */
// This GlobalAuth file is required because it requires the ReduxProvider wrapped around it

import useFetchUser from "@/features/auth/hooks/useFetchUser";

const GlobalAuth = () => {
  useFetchUser();
  return null;
};

export default GlobalAuth;
