import Image from "next/image";

export function ProviderFavicon({
  src,
  size = 36,
}: {
  /** The provider's icon, as the catalog serves it. */
  src: string;
  size?: number;
}) {
  return (
    <Image
      src={src}
      alt=""
      width={size}
      height={size}
      className="rounded-xl object-contain"
      unoptimized
    />
  );
}
