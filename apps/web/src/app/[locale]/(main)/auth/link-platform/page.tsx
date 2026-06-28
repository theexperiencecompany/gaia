import LinkPlatformClient from "@/app/[locale]/(main)/auth/link-platform/client";

interface LinkPlatformPageProps {
  searchParams: Promise<{ platform?: string; token?: string }>;
}

export default async function LinkPlatformPage({
  searchParams,
}: LinkPlatformPageProps) {
  const { platform, token } = await searchParams;

  return (
    <LinkPlatformClient platform={platform ?? null} token={token ?? null} />
  );
}
