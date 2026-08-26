"use client";

import Image from "next/image";
import { type ReactNode, useState } from "react";

import HeroImage from "@/features/landing/components/hero/HeroImage";
import {
  getTimeOfDay,
  type TimeOfDay,
} from "@/features/landing/utils/timeOfDay";

interface AuthShellProps {
  title: string;
  subtitle: string;
  children: ReactNode;
}

/**
 * Full-screen backdrop + centered glass card shared by the local-mode
 * login and signup pages. Matches the existing auth surfaces (desktop-login,
 * RedirectLoader): time-of-day wallpaper behind a frosted zinc card with the
 * GAIA wordmark and a PP Editorial heading.
 */
export function AuthShell({ title, subtitle, children }: AuthShellProps) {
  const [timeOfDay] = useState<TimeOfDay>(() => getTimeOfDay());

  return (
    <div className="relative flex min-h-screen w-full items-center justify-center">
      <div className="fixed inset-0 z-0 opacity-60">
        <HeroImage timeOfDay={timeOfDay} />
      </div>

      <div className="relative z-10 w-full max-w-md px-6">
        <div className="flex flex-col rounded-4xl bg-zinc-100/10 p-8 backdrop-blur-lg">
          <div className="mb-6 flex justify-center">
            <Image
              src="/images/logos/text_w_logo_white.webp"
              alt="GAIA"
              width={120}
              height={36}
              priority
            />
          </div>

          <h1 className="mb-1 text-center font-serif text-4xl font-normal text-white">
            {title}
          </h1>
          <p className="mb-8 text-center text-sm font-light text-zinc-300">
            {subtitle}
          </p>

          {children}
        </div>
      </div>
    </div>
  );
}
