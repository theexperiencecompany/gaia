"use client";

import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import HeroImage from "@/features/landing/components/hero/HeroImage";
import {
  getTimeOfDay,
  type TimeOfDay,
} from "@/features/landing/utils/timeOfDay";

interface RedirectLoaderProps {
  url: string;
  external?: boolean;
  replace?: boolean;
}

export function RedirectLoader({ url, replace = false }: RedirectLoaderProps) {
  const router = useRouter();
  const [timeOfDay, setTimeOfDay] = useState<TimeOfDay | null>(null);

  useEffect(() => {
    setTimeOfDay(getTimeOfDay());
  }, []);

  useEffect(() => {
    const navigator = replace ? router.replace : router.push;
    navigator(url);
  }, [url, router, replace]);

  return (
    <div className="inset-0 flex h-full flex-1 flex-col items-center justify-center">
      <div className="fixed left-0 top-0 h-screen w-screen opacity-30 z-0">
        <HeroImage timeOfDay={timeOfDay} />
      </div>

      <div className="mb-6 animate-spin">
        <Image
          src="/images/logos/logo.webp"
          alt="GAIA"
          width={80}
          height={80}
          priority
        />
      </div>
      <div className="text-lg font-normal text-white">Redirecting you...</div>
    </div>
  );
}
