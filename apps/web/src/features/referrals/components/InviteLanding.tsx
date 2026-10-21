import { Avatar } from "@heroui/avatar";
import type {
  ReferralCopyVariant,
  ReferralResolveResponse,
} from "@shared/api/generated";
import Image from "next/image";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import { REFERRAL_COPY, REFERRAL_UI_COPY } from "../referralCopy";
import { offerPrices } from "../utils/offerPrices";

/** The same wallpaper as the invite's link preview, so the click lands where the card promised. */
const INVITE_WALLPAPER = "/images/wallpapers/bands_gradient_black.png";

interface InviteLandingProps {
  /** Null when the code could not be resolved: the page still offers a way in. */
  invite: ReferralResolveResponse | null;
  copyVariant: ReferralCopyVariant;
  signupHref: string;
}

/** Face, gift headline, price, one button, on the landing hero panel. An invalid code still lands on a way in. */
export function InviteLanding({
  invite,
  copyVariant,
  signupHref,
}: InviteLandingProps) {
  const referrer = invite?.valid ? invite.referrer_first_name : null;
  const prices = invite ? offerPrices(invite.offer) : null;

  return (
    <main className="w-full bg-primary-bg p-3 sm:p-6">
      <div className="relative flex min-h-[calc(100dvh-1.5rem)] w-full flex-col items-center justify-center overflow-hidden rounded-[2.5rem] px-6 py-24 sm:min-h-[calc(100dvh-3rem)]">
        <Image
          src={INVITE_WALLPAPER}
          alt=""
          fill
          priority
          sizes="100vw"
          className="z-0 object-cover object-bottom"
        />
        <div className="pointer-events-none absolute inset-0 z-10 bg-black/20" />
        <div className="pointer-events-none absolute inset-0 z-30 rounded-[2.5rem] border-2 border-white/10" />

        <div className="relative z-20 flex w-full max-w-3xl flex-col items-center text-center">
          {referrer && (
            <div className="mb-10 flex items-center gap-3 rounded-full bg-white/10 py-1.5 pr-5 pl-1.5 backdrop-blur-xl">
              <Avatar
                src={invite?.referrer_picture ?? undefined}
                name={referrer}
                size="sm"
                className="size-9"
              />
              <span className="text-sm text-zinc-100">
                {REFERRAL_UI_COPY.landingFrom(referrer)}
              </span>
            </div>
          )}

          <h1 className="font-serif text-[clamp(2.8rem,8vw,5rem)] leading-[1.05] font-normal tracking-tight text-balance text-white">
            {referrer
              ? REFERRAL_COPY[copyVariant].landing.title(referrer)
              : REFERRAL_UI_COPY.landingFallbackTitle}
          </h1>

          {referrer && prices && (
            <p className="mt-6 text-lg leading-7 font-light text-zinc-200 tabular-nums sm:text-2xl sm:leading-8">
              <span className="mr-2 text-zinc-400 line-through decoration-zinc-400/70">
                {prices.regular}
              </span>
              {REFERRAL_UI_COPY.landingPrice(prices)}
            </p>
          )}

          <div className="mt-10">
            <GetStartedButton
              href={signupHref}
              text={
                referrer
                  ? REFERRAL_UI_COPY.landingCta
                  : REFERRAL_UI_COPY.landingFallbackCta
              }
              classname="h-12 px-6 text-base text-black!"
            />
          </div>
        </div>
      </div>
    </main>
  );
}
