import Link from "next/link";
import { ChevronRight } from "@/components";
import ShinyText from "@/components/ui/shimmering-chip";
import { MotionContainer } from "@/layouts/MotionContainer";
import GetStartedButton from "../shared/GetStartedButton";
import { SplitTextBlur } from "./SplitTextBlur";

export default function HeroSection() {
  // const { data: release, isLoading: isReleaseLoading } = useLatestRelease(
  //   "theexperiencecompany/gaia",
  // );

  return (
    <div className="relative w-screen flex-col gap-8 pb-40">
      <MotionContainer
        className="relative z-2 flex h-full flex-col items-center justify-start gap-4 bg-transparent"
        staggerDelay={0.07}
        disableIntersectionObserver={true}
      >
        <div className="mx-auto flex w-full justify-center gap-2">
          {/* <Link href="https://github.com/theexperiencecompany/gaia/releases">
            <div className="relative z-10 flex w-fit cursor-pointer items-center gap-2 rounded-full bg-white/40 text-zinc-700 p-1 px-4 pl-1 text-sm font-light outline-1 outline-white/50  hover:outline-zinc-200 transition">
              <Github width={20} height={20} />
              <ShinyText
                heading="New: "
                text={`${isReleaseLoading ? "Loading..." : release?.name}`}
                speed={10}
              />
            </div>
          </Link> */}

          <Link href="/blog/public-beta">
            <div className="relative z-10 flex w-fit cursor-pointer items-center gap-1 rounded-full bg-white/40 text-zinc-700 p-1 px-2 text-sm outline-1 outline-white/50  transition mb-2 hover:scale-105 duration-300 backdrop-blur-xl">
              <ShinyText text={`Currently in Public Beta`} speed={10} />
              <ChevronRight width={15} height={15} />
            </div>
          </Link>
        </div>
        <SplitTextBlur
          text="You shouldn't be doing this manually."
          // text="Meet the personal assistant you've always wanted"
          delay={0}
          staggerDelay={0.15}
          className="max-w-(--breakpoint-lg) text-center text-[2.8rem] leading-none sm:text-[6.5rem] font-normal tracking-tighter overflow-visible"
          gradient="linear-gradient(to bottom, oklch(55.2% 0.016 285.938), #000000)"
          disableIntersectionObserver
          as="h1"
          // showGlowTextBg
        />

        <div className="relative">
          <div className="mb-6 max-w-(--breakpoint-lg) px-4 py-0 text-center text-lg leading-7 font-normal tracking-tighter text-black sm:px-0 sm:text-xl">
            GAIA handles your emails, tasks, calendar, and workflows,
            <br /> so you can focus on work that actually matters.
          </div>
          <div className="mb-6 absolute top-0 blur-sm max-w-(--breakpoint-lg) px-4 py-0 text-center text-lg leading-7 font-normal tracking-tighter text-white z-[-1] sm:px-0 sm:text-xl">
            GAIA handles your emails, tasks, calendar, and workflows,
            <br /> so you can focus on work that actually matters.
          </div>
          <div className="mb-6 absolute top-0 blur-lg max-w-(--breakpoint-lg) px-4 py-0 text-center text-lg leading-7 font-normal tracking-tighter text-white z-[-1] sm:px-0 sm:text-xl">
            GAIA handles your emails, tasks, calendar, and workflows,
            <br /> so you can focus on work that actually matters.
          </div>
        </div>
        <div className="flex gap-4">
          <GetStartedButton
            btnColor={"#000000"}
            classname="text-white! text-lg h-12 px-2 rounded-2xl"
            text="Try GAIA Free"
          />
        </div>
      </MotionContainer>
    </div>
  );
}
