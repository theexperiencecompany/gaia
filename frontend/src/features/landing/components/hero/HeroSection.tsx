import { ArrowRight } from "lucide-react";
import Link from "next/link";

import { Github } from "@/components";
import ShinyText from "@/components/ui/shadcn/shimmering-chip";
import { useLatestRelease } from "@/hooks/useLatestRelease";
import { MotionContainer } from "@/layouts/MotionContainer";

import GetStartedButton from "../shared/GetStartedButton";
import { SplitTextBlur } from "./SplitTextBlur";

export default function HeroSection() {
  const { data: release, isLoading: isReleaseLoading } =
    useLatestRelease("heygaia/gaia");

  return (
    <div className="relative w-screen flex-col gap-8 pb-14">
      {/* <div className="relative mt-28 w-screen flex-col gap-8 py-16 sm:pb-10"> */}

      {/* <div className="particles absolute top-0 z-1 h-screen w-full overflow-hidden bg-[#00bbff50] bg-[radial-gradient(circle_at_center,_#00bbff50_0%,_#00bbff50_40%,_#01bbff0d_75%,_transparent_100%)]">

        <div className="vignette absolute h-[351%] w-full bg-[radial-gradient(circle,_rgba(0,0,0,0)_0%,_rgba(0,0,0,0)_47%,_#000_80%)]" />
      </div> */}

      <MotionContainer
        className="relative z-2 flex h-full flex-col items-center justify-start gap-4 bg-transparent"
        staggerDelay={0.07}
        disableIntersectionObserver={true}
      >
        <div className="mx-auto flex w-full justify-center gap-2">
          <Link href="https://github.com/heygaia/gaia/blob/master/CHANGELOG.md">
            <div className="relative z-10 flex w-fit cursor-pointer items-center gap-2 rounded-full bg-zinc-900 p-1 px-3 pl-1 text-sm font-light outline-1 outline-zinc-800 transition-colors hover:bg-zinc-800">
              <Github width={20} height={20} />
              <ShinyText
                text={`New: ${isReleaseLoading ? "" : release?.name.replace("-beta", "")}`}
                speed={10}
              />
            </div>
          </Link>

          <Link href="/blog/public-beta">
            <div className="relative z-10 flex w-fit cursor-pointer items-center gap-2 rounded-full bg-zinc-900 p-1 px-4 text-sm font-light outline-1 outline-zinc-800 transition-colors hover:bg-zinc-800">
              <ShinyText text={`Public Beta`} speed={10} />
              <ArrowRight width={15} height={15} className="text-zinc-400" />
            </div>
          </Link>
        </div>

        <SplitTextBlur
          text="Meet the personal assistant you’ve always wanted"
          delay={0}
          staggerDelay={0.15}
          className="z-[10] max-w-(--breakpoint-lg) text-center text-[2.8rem] leading-none sm:text-8xl"
          disableIntersectionObserver
        />
        <div className="mb-6 max-w-(--breakpoint-sm) px-4 py-0 text-center text-lg leading-7 font-light tracking-tighter text-foreground-700 sm:px-0 sm:text-xl">
          Tired of Siri, Google Assistant, and ChatGPT doing nothing useful?
        </div>

        <div className="flex gap-4">
          <GetStartedButton />

          {/* <Link href={"/manifesto"}>
            <Button className="rounded-xl bg-black/20 px-8! py-5 text-sm! font-light text-zinc-300 backdrop-blur-2xl! transition-all! duration-200 hover:scale-110 hover:bg-black/40">
              Read the Manifesto <ArrowRight width={20} height={20} />
            </Button>
          </Link> */}
        </div>
      </MotionContainer>
    </div>
  );
}
