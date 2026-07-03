"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";

import Spinner from "@/components/ui/spinner";
import { authApi } from "@/features/auth/api/authApi";
import { handleAuthLogin } from "@/features/auth/hooks/handleAuthLogin";
import { apiauth } from "@/lib/api/client";

interface ShortLinkResolverProps {
  slug: string;
}

/**
 * Resolves a heygaia.link slug for the signed-in viewer. The API route
 * (`/l/{slug}`) viewer-scopes the slug and redirects to the artifact, so once
 * the viewer is known to be authenticated we hand the browser off to it. An
 * unauthenticated viewer bounces through login and returns here afterward.
 *
 * The `["current-user"]` query is the same one GlobalAuth runs, so this reads
 * the shared auth state rather than firing a second request.
 */
export default function ShortLinkResolver({ slug }: ShortLinkResolverProps) {
  const { isSuccess, isError } = useQuery({
    queryKey: ["current-user"],
    queryFn: () => authApi.fetchUserInfo(),
    staleTime: Infinity,
    retry: false,
  });

  useEffect(() => {
    if (isSuccess) {
      window.location.assign(`${apiauth.getUri()}l/${slug}`);
    } else if (isError) {
      handleAuthLogin(`/l/${slug}`);
    }
  }, [isSuccess, isError, slug]);

  return (
    <div className="flex h-full w-full items-center justify-center">
      <Spinner />
    </div>
  );
}
