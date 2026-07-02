import LinkPlatformClient from "@/app/[locale]/(main)/auth/link-platform/client";

interface LinkPlatformPageProps {
  searchParams: Promise<{
    platform?: string | string[];
    token?: string | string[];
  }>;
}

/**
 * searchParams surfaces duplicate query keys as `string[]`; the client expects a
 * single string. Collapse to the first value (or null) so the platform lookup
 * and API call always receive the right shape.
 */
function firstValue(value: string | string[] | undefined): string | null {
  if (Array.isArray(value)) return value[0] ?? null;
  return value ?? null;
}

export default async function LinkPlatformPage({
  searchParams,
}: Readonly<LinkPlatformPageProps>) {
  const { platform, token } = await searchParams;

  return (
    <LinkPlatformClient
      platform={firstValue(platform)}
      token={firstValue(token)}
    />
  );
}
