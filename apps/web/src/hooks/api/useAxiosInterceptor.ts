"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { apiauth } from "@/lib/api/client";
import { toast } from "@/lib/toast";
import { processAxiosError } from "@/utils/interceptorUtils";

/**
 * Mount only inside the (main) app shell — landing pages must not surface
 * background-fetch error toasts to anonymous visitors.
 */
export default function useAxiosInterceptor() {
  const router = useRouter();

  useEffect(() => {
    const interceptor = apiauth.interceptors.response.use(
      (response) => response,
      (error) => {
        try {
          processAxiosError(error, { router });
        } catch (handlerError) {
          console.error("Error handling axios interceptor:", handlerError);
          toast.error("An unexpected error occurred.");
        }
        return Promise.reject(error);
      },
    );

    return () => {
      apiauth.interceptors.response.eject(interceptor);
    };
  }, [router]);
}
