import Image from "next/image";

import { Button } from "@/components/ui/button";
import { SectionHeading } from "@/features/landing/layouts/SectionHeader";
import { Call02Icon, ChatBotIcon, VoiceIcon } from "@/icons";

export default function MobileSection() {
  return (
    <div className="flex w-screen flex-col items-center justify-center">
      <div className="relative z-1 flex max-h-[430px] w-screen max-w-fit flex-col items-start justify-center space-y-5 overflow-hidden rounded-3xl bg-zinc-950 pl-12 sm:flex-row">
        <div className="flex flex-col">
          <SectionHeading
            heading="Move beyond Siri and Google Assistant"
            className="mt-10"
            chipTitle2="Coming Soon"
            smallHeading
            subheading="Ever been frustrated with your personal assistant not working as expected? Finally, a personal assistant that 'just works' and more."
          />

          <div className="relative z-1 flex w-full flex-col gap-2 px-6 py-8 pt-0 sm:pt-8">
            <div className="flex flex-row gap-2">
              <ChatBotIcon className="text-primary" />
              <span className="text-zinc-300">
                Set GAIA as your default AI assistant
              </span>
            </div>

            <div className="flex flex-row gap-2">
              <VoiceIcon className="text-primary" />
              <span className="text-zinc-300">
                Activate with
                <span className="ml-2 rounded-md bg-primary/20 px-2 py-1 text-primary">
                  Hey GAIA
                </span>
              </span>
            </div>
            <div className="flex flex-row gap-2">
              <Call02Icon className="text-primary" />
              <span className="text-zinc-300">Automate phone calls</span>
            </div>
          </div>

          <div className="relative z-1 flex justify-center gap-2 px-5 sm:justify-start sm:px-0">
            <Button
              className="flex h-[60px] rounded-xl border-2 border-white/30 bg-black text-white"
              aria-label="Download GAIA from App Store - Coming Soon"
            >
              <div className="flex flex-row items-center gap-4">
                <Image
                  src="/images/icons/apple.svg"
                  alt="Apple Icon"
                  width={30}
                  height={30}
                  loading="lazy"
                />

                <div className="flex flex-col items-start pr-3">
                  <div className="text-xs font-normal text-white/60 sm:text-sm">
                    COMING SOON
                  </div>
                  <div className="text-md font-medium sm:text-lg">
                    App Store
                  </div>
                </div>
              </div>
            </Button>

            <Button
              className="flex h-[60px] rounded-xl border-2 border-white/30 bg-black text-white"
              aria-label="Download GAIA from Google Play Store - Coming Soon"
            >
              <div className="flex flex-row items-center gap-4">
                <Image
                  src="/images/icons/google_play.svg"
                  alt="Play Store Icon"
                  width={27}
                  height={27}
                  loading="lazy"
                />
                <div className="flex flex-col items-start pr-3">
                  <div className="text-xs font-normal text-white/60 sm:text-sm">
                    COMING SOON
                  </div>
                  <div className="text-md font-medium sm:text-lg">
                    Google Play
                  </div>
                </div>
              </div>
            </Button>
          </div>
        </div>
        {/* <Iphone15Pro
          className="relative z-2 h-fit px-5 sm:max-h-[70vh]"
          src="/landing/mobile_screenshot.webp"
        /> */}
      </div>
    </div>
  );
}
