"use client";

/**
 * Mounts global, route-agnostic listeners that need to run anywhere the
 * user might land after an external redirect (OAuth, etc.).
 *
 * Axios error handling is NOT mounted here — it lives in
 * `useAxiosInterceptor`, called only inside the (main) app shell, so
 * background-fetch errors never surface toasts on landing pages.
 */

import { useOAuthSuccessToast } from "@/hooks/useOAuthSuccessToast";

const GlobalInterceptor = () => {
  useOAuthSuccessToast();
  return null;
};

export default GlobalInterceptor;
