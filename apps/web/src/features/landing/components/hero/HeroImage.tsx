import ProgressiveImage from "@/components/ui/ProgressiveImage";

export default function HeroImage({
  shouldHaveInitialFade = false,
}: {
  shouldHaveInitialFade?: boolean;
}) {
  return (
    <ProgressiveImage
      webpSrc="/images/wallpapers/g3.webp"
      pngSrc="/images/wallpapers/g3.png"
      alt="wallpaper"
      className="object-cover"
      shouldHaveInitialFade={shouldHaveInitialFade}
    />
  );
}
