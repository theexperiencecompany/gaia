import Link from "next/link";
import { ChevronRight } from "@/components";
import ShinyText from "@/components/ui/shimmering-chip";
import { MotionContainer } from "@/layouts/MotionContainer";
import GetStartedButton from "../shared/GetStartedButton";
import { SplitTextBlur } from "./SplitTextBlur";

export default function HeroSection({
  isDark = false,
  onTextClick,
}: {
  isDark?: boolean;
  onTextClick?: () => void;
}) {
  return (
    <div className="relative w-full flex-col gap-8 pb-20 sm:pb-40">
      <MotionContainer
        className="relative z-2 flex h-full flex-col items-center justify-start gap-4 bg-transparent"
        staggerDelay={0.07}
        disableIntersectionObserver={true}
      >
        <div className="mx-auto flex w-full justify-center gap-2">
          <Link href="/blog/public-beta">
            <div className="relative z-10 flex w-fit cursor-pointer items-center gap-1 rounded-full bg-white/40 text-zinc-700 p-1 px-2 text-sm outline-1 outline-white/50  transition mb-2 hover:scale-105 duration-300 backdrop-blur-xl">
              <ShinyText text={`Currently in Public Beta`} speed={10} />
              <ChevronRight width={15} height={15} />
            </div>
          </Link>
        </div>

        <div onClick={onTextClick} className="cursor-default select-none">
          {isDark ? (
            <SplitTextBlur
              text="You shouldn't be doing this manually."
              delay={0}
              staggerDelay={0.08}
              className="max-w-(--breakpoint-lg) text-center text-[2.8rem] leading-none sm:text-[6.5rem] font-normal tracking-tighter overflow-visible"
              gradient="linear-gradient(to bottom, #ffffff, #dbdbdb)"
              disableIntersectionObserver
              as="h1"
            />
          ) : (
            <SplitTextBlur
              text="You shouldn't be doing this manually."
              delay={0}
              staggerDelay={0.08}
              className="max-w-(--breakpoint-lg) text-center text-[2.8rem] leading-none sm:text-[6.5rem] font-normal tracking-tighter overflow-visible"
              gradient="linear-gradient(to bottom, #837e88, #000000)"
              disableIntersectionObserver
              as="h1"
            />
          )}
        </div>

        <div className="relative">
          <div
            className={`mb-3 max-w-(--breakpoint-lg) px-4 py-0 text-center text-lg leading-7 font-light tracking-tighter sm:px-0 sm:text-xl ${isDark ? "text-zinc-200" : "text-black"}`}
          >
            GAIA handles your emails, tasks, calendar, and workflows,
            <br /> so you can focus on work that actually matters.{" "}
          </div>
        </div>
        <div className="flex gap-4">
          <GetStartedButton
            btnColor={isDark ? "#00bbff" : "#000000"}
            classname={
              isDark
                ? "text-black! text-lg h-12 px-2 rounded-2xl"
                : "text-white! text-lg h-12 px-2 rounded-2xl"
            }
            text="Try GAIA Free"
          />
        </div>
      </MotionContainer>
    </div>
  );
}
