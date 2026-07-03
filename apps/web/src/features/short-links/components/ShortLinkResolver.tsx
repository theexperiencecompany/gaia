"use client";

import { useQuery } from "@tanstack/react-query";
import axios from "axios";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import Spinner from "@/components/ui/spinner";
import { authApi } from "@/features/auth/api/authApi";
import { handleAuthLogin } from "@/features/auth/hooks/handleAuthLogin";
import { apiService } from "@/lib/api/service";

interface ShortLinkResolverProps {
  slug: string;
}

/**
 * Resolves a heygaia.link slug for the signed-in viewer, then navigates to the
 * artifact it points at. Resolution goes through the app's authed API client
 * (same-origin cookie, correct `/api/v1` base) and the returned path is a
 * client-side `router.replace`, so dev and prod behave identically and the
 * viewer never sees a raw API response.
 *
 * Auth reuses the shared `["current-user"]` query (the one GlobalAuth runs): a
 * signed-out viewer bounces through login and returns here to finish resolving.
 */
export default function ShortLinkResolver({ slug }: ShortLinkResolverProps) {
  const router = useRouter();
  const [notFound, setNotFound] = useState(false);

  const { isSuccess, isError } = useQuery({
    queryKey: ["current-user"],
    queryFn: () => authApi.fetchUserInfo(),
    staleTime: Infinity,
    retry: false,
  });

  useEffect(() => {
    if (isError) {
      handleAuthLogin(`/l/${slug}`);
      return;
    }
    if (!isSuccess) return;

    let cancelled = false;
    apiService
      .get<{ path: string }>(`/l/${slug}`, { silent: true })
      .then((res) => {
        if (!cancelled) router.replace(res.path);
      })
      .catch((error) => {
        // 404 = the slug isn't this viewer's (viewer-scoped) — nothing to open.
        // Other statuses (e.g. a rare mid-flight 401) are owned by the shared
        // response interceptor.
        if (
          !cancelled &&
          axios.isAxiosError(error) &&
          error.response?.status === 404
        ) {
          setNotFound(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [isSuccess, isError, slug, router]);

  if (notFound) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-2 text-center">
        <p className="text-sm text-zinc-400">This link is not available.</p>
        <p className="text-xs text-zinc-500">
          It may have expired, or it belongs to a different account.
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full w-full items-center justify-center">
      <Spinner />
    </div>
  );
}
