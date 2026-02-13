import Link from "next/link";
import { ChevronRight } from "@/components";
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
    <div className="relative w-full flex-col gap-8 pb-20 sm:pb-30">
      <MotionContainer
        className="relative z-2 flex h-full flex-col items-center justify-start gap-4 bg-transparent"
        staggerDelay={0.07}
        disableIntersectionObserver={true}
      >
        <div className="mx-auto flex w-full justify-center gap-2">
          <Link href="/blog/public-beta">
            <div
              className={`relative z-10 flex w-fit cursor-pointer font-light items-center gap-1 rounded-full  ${isDark ? "text-white bg-zinc-400/30  outline-zinc-400/40" : "text-zinc-700 bg-white/40  outline-white/50"}  p-1 px-2 text-sm outline-1  transition mb-2 hover:scale-105 duration-300 backdrop-blur-xl`}
            >
              <span>Currently in Public Beta</span>
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
      </MotionContainer>

      {/* Subtitle + CTA rendered outside MotionContainer to avoid stagger delay (LCP fix) */}
      <div className="relative z-2 flex flex-col items-center gap-4 bg-transparent">
        <div className="relative">
          <div
            className={`mb-3 max-w-(--breakpoint-lg) px-4 py-0 text-center text-lg leading-7 tracking-tighter sm:px-0 sm:text-xl animate-[fadeIn_0.4s_ease-out_0.2s_both] ${isDark ? "text-zinc-200" : "text-black"}`}
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
      </div>
    </div>
  );
}
