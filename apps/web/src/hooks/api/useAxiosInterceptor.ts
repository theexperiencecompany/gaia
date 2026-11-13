"use client";

import { useRouter } from "next/navigation";
import { useLayoutEffect } from "react";

import { registerApiErrorHandler } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { processAxiosError } from "@/utils/interceptorUtils";

/**
 * Mount only inside the (main) app shell — landing pages must not surface
 * background-fetch error toasts to anonymous visitors.
 *
 * A layout effect: axios binds a request to the interceptors registered when it
 * is sent, and descendants send their first queries from passive effects that
 * run before this component's own, so those would skip the handler.
 */
export default function useAxiosInterceptor() {
  const router = useRouter();

  useLayoutEffect(
    () =>
      registerApiErrorHandler((error) => {
        try {
          processAxiosError(error, { router });
        } catch (handlerError) {
          console.error("Error handling axios interceptor:", handlerError);
          toast.error("An unexpected error occurred.");
        }
      }),
    [router],
  );
}
