import { Chip } from "@heroui/chip";
import { m } from "motion/react";
import ProgressiveImage from "@/components/ui/ProgressiveImage";
import GetStartedButton from "../../shared/GetStartedButton";

const ease = [0.22, 1, 0.36, 1] as const;

export default function Hero() {
  return (
    <section className="relative flex min-h-screen flex-col items-center justify-center overflow-hidden px-6 pb-16 pt-24 text-center">
      <div className="absolute inset-0 -z-10">
        <ProgressiveImage
          webpSrc="/images/wallpapers/bands_gradient_1.webp"
          pngSrc="/images/wallpapers/bands_gradient_1.png"
          alt="Gradient background"
          className="object-cover"
          shouldHaveInitialFade
          priority
        />
      </div>

      <m.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease }}
        className="relative z-10 mb-6"
      >
        <Chip variant="flat" color="primary" size="md">
          For Founders
        </Chip>
      </m.div>
      <m.h1
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.1 }}
        className="font-serif relative z-10 mb-6 max-w-4xl text-5xl font-normal leading-[1.1] text-white sm:text-6xl md:text-7xl"
      >
        Your startup runs on 20 tools.
        <br />
        Now it runs on one.
      </m.h1>
      <m.p
        initial={{ opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.2 }}
        className="relative z-10 mb-10 max-w-2xl text-xl font-light leading-relaxed text-white"
      >
        GAIA connects to your inbox, Slack, calendar, CRM, and 30+ tools — then
        does the grunt work for you, automatically.
      </m.p>
      <m.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, ease, delay: 0.3 }}
        className="relative z-10"
      >
        <GetStartedButton
          text="See it in action"
          btnColor="#000000"
          classname="text-white! text-base h-12 rounded-2xl"
        />
      </m.div>
    </section>
  );
}
