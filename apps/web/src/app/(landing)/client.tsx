"use client";

import { LandingDownloadSection } from "@/features/download/components/DownloadPage";
import ChatDemoSection from "@/features/landing/components/demo/ChatDemoSection";
import HeroImage from "@/features/landing/components/hero/HeroImage";
import HeroSection from "@/features/landing/components/hero/HeroSection";
import CommunitySection from "@/features/landing/components/sections/CommunitySection";
import FinalSection from "@/features/landing/components/sections/FinalSection";
import OpenSource from "@/features/landing/components/sections/OpenSource";
import Personalised from "@/features/landing/components/sections/Personalised";
import Productivity from "@/features/landing/components/sections/Productivity";
import TiredBoringAssistants from "@/features/landing/components/sections/TiredBoringAssistants";
import WorkflowSection from "@/features/landing/components/sections/WorkflowSection";
import { FAQAccordion } from "@/features/pricing/components/FAQAccordion";
import { useEffect } from "react";
import Image from "next/image";

export default function LandingPageClient() {
  useEffect(() => {
    document.documentElement.style.overflowY = "scroll";

    return () => {
      document.documentElement.style.overflowY = "auto";
    };
  }, []);

  // const imageOptions = [
  //   {
  //     name: "Calendar",
  //     src: "/images/screenshots/calendar.webp",
  //   },
  //   {
  //     name: "Chats",
  //     src: "/images/screenshots/chats.png",
  //   },
  //   {
  //     name: "Todos",
  //     src: "/images/screenshots/todos.webp",
  //   },
  //   {
  //     name: "Goals",
  //     src: "/images/screenshots/goals.png",
  //   },
  //   {
  //     name: "Mail",
  //     src: "/images/screenshots/mail.webp",
  //   },
  // ];

  return (
    <div className="relative overflow-hidden">
      <div className="absolute inset-0 h-screen w-full opacity-100">
        <HeroImage />
      </div>

      <section className="relative z-20 flex min-h-screen w-full flex-col items-center justify-center">
        <HeroSection />
      </section>

      <section className="relative z-20 w-full py-20 mb-30">
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 h-[10vh] bg-linear-to-b from-black to-transparent" />

        <Image
          src="/images/wallpapers/bands_gradient_1.png"
          alt=""
          fill
          className="object-cover absolute top-0 left-0 -z-10 opacity-90"
          priority
        />
        <ChatDemoSection />
      </section>

      <div>
        <TiredBoringAssistants />
        {/* <div className="relative">

          <div
            className="absolute top-140 z-0 h-[120vh] w-screen blur-lg"
            style={{
              backgroundImage: `
              radial-gradient(circle at center, #00bbff80 0%, transparent 70%)
              `,
              opacity: 0.6,
            }}
          />
        </div> */}

        {/* <ProductivityOS /> */}
        {/* <ToolsShowcaseSection /> */}
        <WorkflowSection />
        <Productivity />
        <Personalised />
        {/* <TestimonialsSection /> */}
        <OpenSource />
        <FAQAccordion />
        <LandingDownloadSection />
        <CommunitySection />
        <FinalSection showSocials={false} />
      </div>
    </div>
  );
}
