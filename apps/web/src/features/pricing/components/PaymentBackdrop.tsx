import Image from "next/image";

import { getImageDimensions } from "@/lib/imageDimensions";

const BACKDROP = getImageDimensions("/images/wallpapers/bands_gradient_1.webp");

/**
 * Full-bleed dark wallpaper for the payment result pages: the shared bands
 * gradient image over the page background, with a soft dark overlay so the
 * glass card stays legible. Decorative — ignores pointer events.
 */
export function PaymentBackdrop() {
  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 overflow-hidden bg-primary-bg"
    >
      <Image
        src="/images/wallpapers/bands_gradient_1.webp"
        alt=""
        width={BACKDROP.width}
        height={BACKDROP.height}
        priority
        sizes="100vw"
        className="absolute inset-0 h-full w-full object-cover"
      />
      {/* Soften for card contrast */}
      <div className="absolute inset-0 bg-primary-bg/15" />
    </div>
  );
}
