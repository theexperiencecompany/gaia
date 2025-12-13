"use client";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";

import { apiauth } from "@/lib/api";
import { isOnLandingRoute, processAxiosError } from "@/utils";

export default function useAxiosInterceptor() {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    // Attach a response interceptor to handle API errors globally
    const interceptor = apiauth.interceptors.response.use(
      (response) => response,
      (error) => {
        try {
          // Process the error and handle authentication or routing side effects
          processAxiosError(error, pathname, {
            router,
          });
        } catch (handlerError) {
          // Log unexpected errors in error handling and show a generic toast if not on landing page
          console.error("Error handling axios interceptor:", handlerError);
          if (!isOnLandingRoute(pathname)) {
            toast.error("An unexpected error occurred.");
          }
        }

        // Reject the promise to propagate the error to the caller
        return Promise.reject(error);
      },
    );

    // Clean up the interceptor on component unmount or dependency change
    return () => {
      apiauth.interceptors.response.eject(interceptor);
    };
  }, [pathname, router]);
}
