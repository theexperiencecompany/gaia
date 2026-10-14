"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { registerApiErrorHandler } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { processAxiosError } from "@/utils/interceptorUtils";

/**
 * Mount only inside the (main) app shell — landing pages must not surface
 * background-fetch error toasts to anonymous visitors.
 */
export default function useAxiosInterceptor() {
  const router = useRouter();

  useEffect(
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
