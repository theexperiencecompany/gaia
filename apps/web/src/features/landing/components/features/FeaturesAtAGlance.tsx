import Link from "next/link";
import {
  CAPABILITY_GROUPS,
  LIMITS,
} from "@/features/landing/data/featuresAtAGlance";
import { ADVERTISED_PRO_MONTHLY_PRICE } from "@/features/pricing/advertisedPrice";

const LINK_CLASS =
  "text-zinc-300 underline-offset-2 hover:text-white hover:underline";

export function FeaturesAtAGlance() {
  return (
    <section className="mx-auto max-w-6xl px-6 pb-16">
      <h2 className="font-serif mb-4 text-4xl font-normal text-white">
        GAIA features at a glance
      </h2>
      <p className="mb-10 max-w-3xl text-base font-light leading-relaxed text-zinc-400">
        GAIA is a proactive personal AI assistant. This is everything it does
        today, in one list.
      </p>
      <div className="grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-3">
        {CAPABILITY_GROUPS.map((group) => (
          <div key={group.heading}>
            <h3 className="mb-3 text-sm font-medium text-zinc-100">
              {group.heading}
            </h3>
            <ul className="space-y-2 text-sm font-light leading-relaxed">
              {group.items.map((item) => (
                <li key={item.text}>
                  <Link href={item.href} className={LINK_CLASS}>
                    {item.text}
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
        <div>
          <h3 className="mb-3 text-sm font-medium text-zinc-100">
            What GAIA does not do
          </h3>
          <ul className="space-y-2 text-sm font-light leading-relaxed text-zinc-300">
            {LIMITS.map((limit) => (
              <li key={limit}>{limit}</li>
            ))}
          </ul>
        </div>
        <div>
          <h3 className="mb-3 text-sm font-medium text-zinc-100">
            Pricing and licence
          </h3>
          <p className="text-sm font-light leading-relaxed text-zinc-300">
            Hosted GAIA is paid: Pro is ${ADVERTISED_PRO_MONTHLY_PRICE} a month
            per person, and GAIA Enterprise is priced on request. The code is
            source-available under the PolyForm Noncommercial license, so you
            can self-host it for personal, noncommercial use; for-profit
            self-hosting needs an enterprise licence.{" "}
            <Link href="/pricing" className={LINK_CLASS}>
              See pricing
            </Link>
          </p>
        </div>
      </div>
    </section>
  );
}
