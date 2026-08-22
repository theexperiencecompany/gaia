"use client";

import {
  AiFileIcon,
  BookOpenIcon,
  CreditCardIcon,
  Home01Icon,
  MapsIcon,
} from "@icons";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { ComponentType } from "react";

import { ChevronLeft } from "@/components/shared/icons";
import { RaisedButton } from "@/components/ui/raised-button";
import { NOT_FOUND_LINKS, type NotFoundLink } from "@/lib/not-found-links";

interface LinkIconProps {
  size?: number;
  color?: string;
}

const LINK_ICONS: Record<NotFoundLink["href"], ComponentType<LinkIconProps>> = {
  "/": Home01Icon,
  "/pricing": CreditCardIcon,
  "/llms.txt": AiFileIcon,
  "/sitemap/0.xml": MapsIcon,
  "https://docs.heygaia.io": BookOpenIcon,
};

export default function PageNotFound() {
  const router = useRouter();

  return (
    <div className="flex h-screen w-screen flex-col items-center justify-center gap-4 bg-linear-to-b from-zinc-900 to-black">
      <div className="absolute z-0 mx-auto w-full text-center text-[40vw] font-bold text-zinc-900/40">
        404
      </div>
      <span className="relative z-1 text-6xl font-medium">Page Not Found</span>
      <span className="relative z-1 text-sm font-light text-zinc-400">
        This page could not be found
      </span>

      <div className="flex items-center gap-3">
        <Link href={"/"}>
          <RaisedButton className="mt-3" color="#2e2e2e">
            <Home01Icon width={18} height={18} color="currentColor" />
            Home
          </RaisedButton>
        </Link>

        <RaisedButton
          className="mt-3 text-black!"
          color="#00bbff"
          onClick={() => router.back()}
        >
          <ChevronLeft width={18} height={18} />
          Go Back
        </RaisedButton>
      </div>

      <nav
        aria-label="Where to look next"
        className="relative z-1 mt-2 flex w-full max-w-md flex-col gap-1 px-6"
      >
        <span className="text-xs font-medium tracking-widest text-zinc-500 uppercase">
          Where to look next
        </span>
        <ul>
          {NOT_FOUND_LINKS.map((link) => {
            const Icon = LINK_ICONS[link.href];
            const rowClassName =
              "group flex items-center gap-3 rounded-xl px-3 py-2 transition-colors hover:bg-zinc-800/60";
            const rowContent = (
              <>
                <Icon size={16} color="currentColor" />
                <span className="min-w-0">
                  <span className="block text-sm font-normal text-zinc-200">
                    {link.name}
                  </span>
                  <span className="block truncate text-xs font-light text-zinc-500">
                    {link.description}
                  </span>
                </span>
              </>
            );

            return (
              <li key={link.href}>
                {link.href.startsWith("/") ? (
                  <Link href={link.href} className={rowClassName}>
                    {rowContent}
                  </Link>
                ) : (
                  <a href={link.href} className={rowClassName}>
                    {rowContent}
                  </a>
                )}
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
