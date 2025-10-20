import Image from "next/image";

import GetStartedButton from "../shared/GetStartedButton";
import LargeHeader from "../shared/LargeHeader";

export default function Tired() {
  return (
    <div className="relative flex h-screen flex-col items-center justify-center gap-2 p-4 sm:p-6 lg:p-10">
      <div
        className="absolute inset-0 z-0 h-full"
        style={{
          backgroundImage: `
          radial-gradient(circle at 50% 100%, rgba(0, 187, 255, 0.1) 0%, transparent 60%),
          radial-gradient(circle at 50% 100%, rgba(255, 255, 255, 0.1) 0%, transparent 70%),
          radial-gradient(circle at 50% 100%, rgba(0, 187, 255, 0.3) 0%, transparent 70%)
        `,
        }}
      />
      <LargeHeader
        headingText="Tired of Boring Assistants?"
        subHeadingText="Meet one that actually works."
        centered
      />

      <div className="relative z-[1] flex gap-6 pt-6 sm:gap-10 sm:pt-8 lg:gap-14 lg:pt-10">
        <Image
          src={"/images/icons/siri.webp"}
          alt="Siri Logo"
          width={70}
          height={70}
          className="size-[50px] translate-y-4 -rotate-8 rounded-xl sm:size-[60px] sm:translate-y-6 sm:rounded-2xl lg:size-[65px] lg:translate-y-7"
        />

        <div className="flex size-[60px] items-center justify-center overflow-hidden rounded-xl sm:size-[70px] sm:rounded-3xl lg:size-[80px]">
          <Image
            src={
              "https://static.vecteezy.com/system/resources/previews/055/687/055/non_2x/rectangle-gemini-google-icon-symbol-logo-free-png.png"
            }
            alt="Gemini Logo"
            width={150}
            className="min-w-[90px]"
            height={150}
          />
        </div>

        <Image
          src={
            "https://static.vecteezy.com/system/resources/previews/024/558/807/non_2x/openai-chatgpt-logo-icon-free-png.png"
          }
          alt="ChatGPT Logo"
          width={70}
          height={70}
          className="size-[50px] translate-y-4 rotate-8 rounded-xl sm:size-[60px] sm:translate-y-6 sm:rounded-2xl lg:size-[65px] lg:translate-y-7"
        />
      </div>

      <Image
        src={"/images/logos/logo.webp"}
        alt="GAIA Logo"
        width={120}
        height={120}
        className="relative z-[1] my-8 h-[100px] w-[100px] rounded-2xl bg-gradient-to-b from-zinc-800 to-zinc-950 p-3 shadow-[0px_0px_100px_40px_rgba(0,_187,_255,_0.2)] outline-1 outline-zinc-800 sm:my-10 sm:h-[110px] sm:w-[110px] sm:rounded-3xl sm:p-4 lg:my-14 lg:h-[120px] lg:w-[120px]"
      />

      <div className="absolute bottom-16 z-[1] flex w-full max-w-xs items-center px-4 sm:bottom-24 sm:max-w-md sm:px-0 lg:bottom-32 lg:max-w-lg">
        <div className="absolute bottom-8 left-0 -rotate-12 rounded-lg bg-zinc-800 px-2 py-1 text-xs text-zinc-500 sm:bottom-12 sm:rounded-xl sm:px-3 sm:py-2 sm:text-sm lg:bottom-16">
          Personalised
        </div>

        <div className="absolute right-0 bottom-8 rotate-12 rounded-lg bg-zinc-800 px-2 py-1 text-xs text-zinc-500 sm:bottom-12 sm:rounded-xl sm:px-3 sm:py-2 sm:text-sm lg:bottom-16">
          Proactive
        </div>

        <div className="absolute bottom-20 left-6 rotate-12 rounded-lg bg-zinc-800 px-2 py-1 text-xs text-zinc-500 sm:bottom-28 sm:left-8 sm:rounded-xl sm:px-3 sm:py-2 sm:text-sm lg:bottom-40 lg:left-10">
          Automated
        </div>

        <div className="absolute right-6 bottom-20 -rotate-12 rounded-lg bg-zinc-800 px-2 py-1 text-xs text-zinc-500 sm:right-8 sm:bottom-28 sm:rounded-xl sm:px-3 sm:py-2 sm:text-sm lg:right-10 lg:bottom-40">
          Integrated
        </div>
      </div>

      <GetStartedButton text="See GAIA in Action" />
    </div>
  );
}
