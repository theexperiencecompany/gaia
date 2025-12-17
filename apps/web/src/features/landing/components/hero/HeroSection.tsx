import Link from "next/link";

import { Github } from "@/components";
import ShinyText from "@/components/ui/shimmering-chip";
import { useLatestRelease } from "@/hooks/useLatestRelease";
import { ChevronRight } from "@/icons";
import { MotionContainer } from "@/layouts/MotionContainer";

import GetStartedButton from "../shared/GetStartedButton";
import { SplitTextBlur } from "./SplitTextBlur";

export default function HeroSection() {
  const { data: release, isLoading: isReleaseLoading } = useLatestRelease(
    "theexperiencecompany/gaia",
  );

  return (
    <div className="relative w-screen flex-col gap-8 pb-30">
      <MotionContainer
        className="relative z-2 flex h-full flex-col items-center justify-start gap-4 bg-transparent"
        staggerDelay={0.07}
        disableIntersectionObserver={true}
      >
        <div className="mx-auto flex w-full justify-center gap-2">
          <Link href="https://github.com/theexperiencecompany/gaia/blob/master/CHANGELOG.md">
            <div className="relative z-10 flex w-fit cursor-pointer items-center gap-2 rounded-full bg-white/40 text-zinc-700 p-1 px-4 pl-1 text-sm font-light outline-1 outline-white/50  hover:outline-zinc-200 hover:shadow-sm shadow-zinc-400 hover:-translate-y-1 transition">
              <Github width={20} height={20} />
              <ShinyText
                heading="New: "
                text={`${isReleaseLoading ? "Loading..." : release?.name}`}
                speed={10}
              />
            </div>
          </Link>

          <Link href="/blog/public-beta">
            <div className="relative z-10 flex w-fit cursor-pointer items-center gap-1 rounded-full bg-white/40 text-zinc-700 p-1 px-2 text-sm font-light outline-1 outline-white/50  hover:outline-zinc-200 hover:shadow-sm shadow-zinc-400 hover:-translate-y-1 transition">
              <ShinyText heading="Status: " text={`Public Beta`} speed={10} />
              <ChevronRight width={15} height={15} />
            </div>
          </Link>
        </div>
        <SplitTextBlur
          text="Meet the personal assistant you’ve always wanted"
          delay={0}
          staggerDelay={0.15}
          className="max-w-(--breakpoint-lg) text-center text-[2.8rem] leading-none sm:text-8xl font-semibold"
          gradient="linear-gradient(to bottom, oklch(55.2% 0.016 285.938), oklch(21% 0.006 285.885))"
          disableIntersectionObserver
          as="h1"
          showGlowTextBg
        />

        <div className="relative">
          <div className="mb-6 max-w-(--breakpoint-sm) px-4 py-0 text-center text-lg leading-7 font-normal tracking-tighter text-white sm:px-0 sm:text-xl">
            Tired of Siri, Google Assistant, and ChatGPT doing nothing useful?
          </div>
          <div className="mb-6 absolute top-0 blur-sm max-w-(--breakpoint-sm) px-4 py-0 text-center text-lg leading-7 font-bold tracking-tighter text-black/60 z-[-1] sm:px-0 sm:text-xl">
            Tired of Siri, Google Assistant, and ChatGPT doing nothing useful?
          </div>
        </div>
        <div className="flex gap-4">
          <GetStartedButton />

          {/* <Link href={"/manifesto"}>
            <Button className="rounded-xl bg-black/20 px-8! py-5 text-sm! font-light text-zinc-300 backdrop-blur-2xl! transition-all! duration-200 hover:scale-110 hover:bg-black/40">
              Read the Manifesto <ArrowRight01Icon width={20} height={20} />
            </Button>
          </Link> */}
        </div>
      </MotionContainer>
    </div>
  );
}
