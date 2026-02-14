"use client";

import { Home01Icon } from "@icons";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronLeft } from "@/components/shared/icons";
import { RaisedButton } from "@/components/ui";

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
    </div>
  );
}
