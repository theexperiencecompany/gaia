import { Button } from "@heroui/button";
import { Call02Icon, ChatBotIcon, VoiceIcon } from "@icons";
import Image from "next/image";
import Link from "next/link";
import { ChevronRight } from "@/components";
import { SectionHeading } from "@/features/landing/layouts/SectionHeader";

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

          <div className="relative z-1 flex flex-col gap-3 px-5 sm:px-0">
            <Button
              as={Link}
              href="https://heygaia.app"
              target="_blank"
              rel="noopener noreferrer"
            >
              Sign up for waitlist <ChevronRight width={17} height={17} />
            </Button>

            <div className="flex flex-wrap gap-2">
              <Button
                variant="flat"
                isDisabled
                startContent={
                  <div className="relative h-4 w-4">
                    <Image
                      src="/images/icons/apple.svg"
                      alt="iOS"
                      fill
                      className="object-contain"
                    />
                  </div>
                }
              >
                App Store
              </Button>
              <Button
                variant="flat"
                isDisabled
                startContent={
                  <div className="relative h-4 w-4">
                    <Image
                      src="/images/icons/google_play.svg"
                      alt="Android"
                      fill
                      className="object-contain"
                    />
                  </div>
                }
              >
                Google Play
              </Button>
            </div>
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
