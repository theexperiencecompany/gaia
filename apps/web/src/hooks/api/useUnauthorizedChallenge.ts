"use client";

import type { AxiosError } from "axios";
import { useEffect } from "react";

import { apiauth } from "@/lib/api/client";
import { useLoginModalStore } from "@/stores/loginModalStore";

/**
 * Opens the login modal whenever an authenticated request returns 401.
 *
 * Mount this ONLY inside the (main) app shell — never from a public/landing
 * provider tree. A 401 on a landing page just means the visitor is anonymous,
 * which is the normal state for marketing routes and must not surface a modal.
 * Inside the app shell, a 401 means the user's session expired mid-action and
 * a re-auth prompt is the right response.
 */
export default function useUnauthorizedChallenge() {
  useEffect(() => {
    const id = apiauth.interceptors.response.use(
      (response) => response,
      (error: AxiosError) => {
        if (error.response?.status === 401) {
          useLoginModalStore.getState().openModal();
        }
        return Promise.reject(error);
      },
    );
    return () => {
      apiauth.interceptors.response.eject(id);
    };
  }, []);
}
