import Image from "next/image";
import { providerFaviconUrl } from "@/features/settings/api/providersApi";

export function ProviderFavicon({
  domain,
  size = 36,
}: {
  domain: string;
  size?: number;
}) {
  return (
    <Image
      src={providerFaviconUrl(domain)}
      alt=""
      width={size}
      height={size}
      className="rounded-xl object-contain"
      unoptimized
    />
  );
}
