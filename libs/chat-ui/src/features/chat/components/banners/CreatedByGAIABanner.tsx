import Image from "next/image";

interface CreatedByGAIABannerProps {
  reason?: string;
  show: boolean;
}

export default function CreatedByGAIABanner({
  reason,
  show,
}: CreatedByGAIABannerProps) {
  if (!show) return null;

  const defaultReason =
    "This conversation appeared automagically, courtesy of GAIA running things behind the scenes.";

  return (
    <div className="mx-auto mb-6 max-w-4xl">
      <div className="rounded-3xl border-1 border-zinc-800 bg-zinc-800/20 p-10">
        <div className="flex flex-col items-center justify-center">
          <Image
            alt="GAIA Logo"
            src="/images/logos/logo.webp"
            width={150}
            height={150}
            className="mb-4 opacity-10 grayscale"
          />

          <div className="text-2xl font-medium">New chat unlocked!</div>

          <p className="max-w-xl text-center leading-relaxed font-light text-foreground-500">
            {reason || defaultReason}
          </p>
        </div>
      </div>
    </div>
  );
}
