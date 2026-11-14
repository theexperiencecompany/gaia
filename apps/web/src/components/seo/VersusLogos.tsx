import Image, { type ImageProps } from "next/image";

/** GAIA's logo tilted against another tool's favicon, leading a comparison or alternative card. */
export function VersusLogos({
  name,
  domain,
  loading,
}: {
  readonly name: string;
  readonly domain: string;
  readonly loading: ImageProps["loading"];
}) {
  return (
    <div className="flex items-center -space-x-2">
      <div
        className="relative flex h-9 w-9 items-center justify-center p-0"
        style={{ rotate: "-9deg", zIndex: 1 }}
      >
        <Image
          src="/images/logos/macos.webp"
          alt="GAIA"
          width={50}
          height={50}
          loading={loading}
        />
      </div>
      <div
        className="relative flex h-8 w-8 items-center justify-center overflow-hidden rounded-md p-0"
        style={{ rotate: "9deg", zIndex: 0 }}
      >
        <Image
          src={`https://www.google.com/s2/favicons?domain=${domain}&sz=128`}
          alt={name}
          width={40}
          height={40}
          loading={loading}
          unoptimized
        />
      </div>
    </div>
  );
}
