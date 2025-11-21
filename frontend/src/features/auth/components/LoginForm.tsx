"use client";

import Image from "next/image";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { FlickeringGrid } from "@/components/ui/magic-ui/flickering-grid";
import { Button } from "@/components/ui/shadcn/button";
import Spinner from "@/components/ui/shadcn/spinner";
import { useUser } from "@/features/auth/hooks/useUser";
import { GoogleColouredIcon } from "@/icons";

import { handleAuthButtonClick } from "../utils/authUtils";

export default function LoginForm() {
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const user = useUser();

  useEffect(() => {
    if (user?.email) router.push("/c");
  }, [user, router]);

  return (
    <form className="relative -bottom-4 flex h-screen w-screen flex-row items-center justify-center gap-10 overflow-auto select-none">
      <div className="0 relative z-1 flex w-full flex-col items-center justify-center gap-5 p-10">
        <div className="mb-3 space-y-3 text-center">
          <div className="text-5xl font-medium">Welcome back!</div>
          <div className="text-lg text-foreground-500">
            GAIA, your personal assistant is ready to help you today.
          </div>
        </div>
        <Button
          className={`text-md gap-2 rounded-full px-4 ${
            loading
              ? "bg-zinc-800 text-primary hover:bg-zinc-800"
              : "bg-white hover:bg-white/20 hover:text-white"
          }`}
          size="lg"
          type="button"
          disabled={loading}
          onClick={() => handleAuthButtonClick(setLoading)}
        >
          {loading ? (
            <>
              <Spinner />
              <span>Loading ...</span>
            </>
          ) : (
            <>
              <GoogleColouredIcon />
              <span>Sign in with Google</span>
            </>
          )}
        </Button>
        <Link href="/signup">
          <Button
            className="gap-2 rounded-full px-4 text-sm font-normal text-primary"
            type="button"
            variant="link"
          >
            New to GAIA? Create an Account
          </Button>
        </Link>
      </div>
      <div className="relative h-full w-[170%]">
        <FlickeringGrid
          className="absolute inset-0 z-0 size-full [mask-image:linear-gradient(to_right,rgba(0,0,0,0),rgba(0,0,0,1),rgba(0,0,0,1))] [mask-size:100%_100%] [mask-repeat:no-repeat]"
          squareSize={4}
          gridGap={8}
          color="#00bbff"
          maxOpacity={0.8}
          flickerChance={0.7}
        />
        <div className="absolute inset-0 flex items-center justify-center">
          <Image
            src={"/landing/screenshot.png"}
            alt="Product screeshot"
            width={1000}
            height={1000}
          />
        </div>
      </div>
    </form>
  );
}
