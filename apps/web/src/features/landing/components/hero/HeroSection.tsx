import { CircleArrowRight02Icon, DiscoverCircleIcon } from "@icons";
import Image from "next/image";
import type { LatestRelease } from "@/features/landing/utils/getLatestRelease";
import { Link } from "@/i18n/navigation";
import { MotionContainer } from "@/layouts/MotionContainer";
import GetStartedButton from "../shared/GetStartedButton";
import { SplitTextBlur } from "./SplitTextBlur";

export default function HeroSection({
  isDark = false,
  onTextClick,
  latestRelease,
}: {
  isDark?: boolean;
  onTextClick?: () => void;
  latestRelease?: LatestRelease | null;
}) {
  return (
    <div className="relative w-full flex-col gap-8 pb-20 sm:pb-30">
      <MotionContainer
        className="relative z-2 flex h-full flex-col items-center justify-start gap-4 bg-transparent"
        staggerDelay={0.07}
        disableIntersectionObserver={true}
      >
        {latestRelease && (
          <div className="mx-auto mb-2 flex w-full justify-center ">
            <Link
              href="https://docs.heygaia.io/release-notes"
              target="_blank"
              rel="noopener noreferrer"
              className="group inline-flex items-center gap-2 text-[13px] hover:bg-white/20 rounded-full px-1 py-1 transition hover:scale-105"
            >
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                  isDark ? "bg-white text-black" : "bg-black text-white"
                }`}
              >
                New
              </span>
              <span
                className={`max-w-[42ch] truncate ${
                  isDark ? "text-zinc-50" : "text-zinc-800"
                }`}
              >
                {latestRelease.headline}
              </span>
              {/* <CircleArrowRight02Icon
                width={17}
                height={17}
                className={`${isDark ? "text-white!" : "text-black!"}`}
              /> */}
            </Link>
          </div>
        )}

        <div onClick={onTextClick} className="cursor-default select-none">
          {isDark ? (
            <SplitTextBlur
              text="Get a workday back every week."
              delay={0}
              staggerDelay={0.08}
              className="max-w-(--breakpoint-lg) text-center text-[2.8rem] leading-none sm:text-[6.5rem] font-normal tracking-tighter overflow-visible"
              gradient="linear-gradient(to bottom, #ffffff, #dbdbdb)"
              lcpOptimized
              disableIntersectionObserver
              as="h1"
            />
          ) : (
            <SplitTextBlur
              text="Get a workday back every week."
              delay={0}
              staggerDelay={0.08}
              className="max-w-(--breakpoint-lg) text-center text-[2.8rem] leading-none -space-y-10 sm:text-[6.5rem] font-normal tracking-tighter overflow-visible"
              gradient="linear-gradient(to bottom, #837e88, #000000)"
              lcpOptimized
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
            className={`mb-3 max-w-(--breakpoint-lg) items-center justify-center gap-x-1.5 gap-y-1 px-4 py-0 text-center text-lg leading-7 tracking-tighter sm:px-0 sm:text-xl animate-[fadeIn_0.4s_ease-out_0.2s_both] ${isDark ? "text-zinc-200" : "text-black"}`}
          >
            <span>
              GAIA watches your inbox, calendar, and tools and acts before you
              ask.
            </span>
            <br />
            <div className="inline-flex flex-wrap items-center justify-center gap-y-1 align-middle">
              <span>Reachable from</span>
              <Link href={"/bots"}>
                <Image
                  src="/images/icons/macos/whatsapp.webp"
                  alt="WhatsApp"
                  className="inline-block size-7 rotate-12 hover:scale-105 transition-transform ml-2"
                  width={100}
                  height={100}
                />
                {/* <span>WhatsApp,</span> */}
                <Image
                  src="/images/icons/macos/slack.webp"
                  alt="Slack"
                  className="inline-block size-7 -rotate-12 hover:scale-105 transition-transform"
                  width={100}
                  height={100}
                />
                {/* <span>Slack,</span> */}
                <Image
                  src="/images/icons/macos/discord.webp"
                  alt="Discord"
                  className="inline-block size-7 rotate-12 hover:scale-105 transition-transform"
                  width={100}
                  height={100}
                />
                {/* <span>Discord,</span> */}
                <Image
                  src="/images/icons/macos/telegram.webp"
                  alt="Telegram"
                  className="inline-block size-7 -rotate-12 hover:scale-105 transition-transform mr-1"
                  width={100}
                  height={100}
                />
                <span>Telegram, </span>
                <span>or the web.</span>
              </Link>
            </div>
          </div>
        </div>
        <div className="flex gap-4 mt-4">
          <GetStartedButton
            btnColor={isDark ? "#00bbff" : "#000000"}
            classname={
              isDark
                ? "text-black! px-1 hover:scale-105"
                : "text-white! px-1 hover:scale-105"
            }
            text={
              <div className="flex items-center gap-1.5">
                Sign Up <CircleArrowRight02Icon width={20} height={20} />
              </div>
            }
          />
          <GetStartedButton
            btnColor="#ffffff"
            classname="px-1 hover:scale-105"
            text={
              <div className="flex items-center gap-1.5">
                Explore <DiscoverCircleIcon width={20} height={20} />
              </div>
            }
            href="/use-cases"
          />
        </div>
      </div>
    </div>
  );
}
