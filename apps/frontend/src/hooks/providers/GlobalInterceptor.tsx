"use client";

/**
 * GlobalInterceptor Component
 *
 * This component isolates the axios interceptor setup to prevent potential
 * server-side rendering issues and organize global side effects.
 *
 * Purpose:
 * 1. Separates axios interceptor logic from the main providers layout
 * 2. Ensures useAxiosInterceptor runs in a controlled client-side context
 * 3. Prevents potential SSR/hydration issues with axios configuration
 * 4. Makes the provider architecture more modular and maintainable
 *
 * The interceptor sets up:
 * - Request/response interceptors for authentication
 * - Error handling for 401/403 responses
 * - Token refresh logic
 * - Request/response logging in development
 *
 * This component returns null since it only performs side effects.
 */

import useAxiosInterceptor from "@/hooks/api/useAxiosInterceptor";

const GlobalInterceptor = () => {
  useAxiosInterceptor();
  return null;
};

export default GlobalInterceptor;
