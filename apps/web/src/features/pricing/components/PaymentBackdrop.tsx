import Image from "next/image";

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
        fill
        priority
        sizes="100vw"
        className="object-cover"
      />
      {/* Soften for card contrast + blend into the page background */}
      <div className="absolute inset-0 bg-primary-bg/40" />
      <div className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-primary-bg to-transparent" />
    </div>
  );
}
