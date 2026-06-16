"use client";

import { Avatar } from "@heroui/avatar";
import { Spinner } from "@heroui/spinner";
import { ArrowRight01Icon } from "@icons";
import { useParams } from "next/navigation";
import { RaisedButton } from "@/components/ui/raised-button";
import { useResolveReferralCode } from "@/features/referrals";
import { RewardTicket } from "@/features/referrals/components/RewardTicket";
import { Link, useRouter } from "@/i18n/navigation";

/**
 * Public invite landing page. Resolving the code (client-side) also arms
 * attribution — the resolve endpoint sets a first-party `gaia_ref` cookie that
 * rides the WorkOS signup redirect. The "Claim" CTA routes to /login, which
 * starts WorkOS; the cookie credits the referrer on the callback.
 *
 * Invalid / expired codes fall back gracefully to a generic "Join GAIA" hero —
 * never an error wall.
 */
export default function InvitePage() {
  const params = useParams();
  const router = useRouter();
  const code = typeof params.code === "string" ? params.code : "";
  const { data, isLoading } = useResolveReferralCode(code);

  if (isLoading) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-primary-bg">
        <Spinner color="primary" />
      </div>
    );
  }

  const valid = data?.valid ?? false;
  const referrerName = data?.referrer_name || "A friend";

  return (
    <div className="relative flex min-h-screen w-full flex-col items-center justify-center overflow-hidden bg-primary-bg px-6 py-16 text-center">
      <div className="animate-scale-in relative z-10 flex w-full max-w-xl flex-col items-center">
        {valid && (
          <div className="mb-7 flex items-center gap-2.5 rounded-full bg-zinc-800/60 py-1.5 pr-4 pl-1.5 backdrop-blur-xl">
            <Avatar
              src={data?.referrer_picture || undefined}
              name={referrerName}
              size="sm"
              className="h-7 w-7 text-xs"
            />
            <span className="text-sm text-zinc-300">
              A gift from {referrerName}
            </span>
          </div>
        )}

        <h1 className="font-serif text-4xl leading-[1.1] font-normal tracking-tight text-white sm:text-6xl">
          {valid ? (
            <>
              {referrerName} gifted you
              <br />
              $30 off GAIA Pro.
            </>
          ) : (
            <>
              Meet GAIA, your proactive
              <br />
              AI assistant.
            </>
          )}
        </h1>

        <p className="mt-6 max-w-md text-base leading-7 font-light text-zinc-400">
          {valid ? (
            <>
              {referrerName} wants to give you their time back. GAIA is your
              proactive AI assistant that quietly handles your email, tasks, and
              follow-ups, so you can focus on what matters.
            </>
          ) : (
            <>
              GAIA quietly handles your email, tasks, calendar, and follow-ups,
              so you can focus on what matters.
            </>
          )}
        </p>

        {valid && (
          <div className="mt-9">
            <RewardTicket
              value="50% OFF"
              caption="First 2 months of GAIA Pro"
              eyebrow="A gift for you"
            />
          </div>
        )}

        <div className="mt-9 flex flex-col items-center gap-3">
          <RaisedButton
            color="#00bbff"
            className="rounded-xl! px-7! text-black!"
            onClick={() => router.push("/login?return_url=/redirect")}
          >
            {valid ? "Claim your gift" : "Get started free"}
            <ArrowRight01Icon width={18} height={18} />
          </RaisedButton>
          <Link
            href="/login"
            className="text-sm text-zinc-500 transition-colors hover:text-zinc-300"
          >
            Already have an account? Log in
          </Link>
        </div>
      </div>
    </div>
  );
}
