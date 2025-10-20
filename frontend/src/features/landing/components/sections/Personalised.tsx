import { AiBrain01Icon } from "@/components";

import MemoryGraphDemo from "../demo/MemoryGraphDemo";
import { SimpleChatBubbleUser } from "../demo/SimpleChatBubbles";
import { BentoItem } from "./TodosBentoContent";
import LargeHeader from "../shared/LargeHeader";

export default function Personalised() {
  const personalInfo = [
    "You work as a Senior Software Engineer at Google",
    "Your girlfriend is Emma Rodriguez, and you've been dating for 2 years",
    "You have a 2-year-old Golden Retriever named Buster",
  ];

  return (
    <div className="flex h-screen flex-col items-center justify-center gap-6 px-4 sm:gap-8 sm:px-6 lg:gap-10 lg:px-8">
      <div className="flex w-full max-w-7xl flex-col items-center justify-center p-4 sm:p-6 lg:p-7">
        <LargeHeader
          centered
          headingText="Finally, AI that feels like it's made for you"
          chipText="Truly Personalised"
        />

        <div className="mx-auto grid w-full max-w-4xl grid-cols-1 grid-rows-1 justify-between gap-4 py-6 sm:gap-6 sm:py-8 lg:grid-cols-2 lg:gap-7 lg:py-10">
          <BentoItem
            title="Recall Everything Instantly"
            description="GAIA remembers every detail you mention in a conversation"
          >
            <div className="flex w-full flex-col gap-2">
              <SimpleChatBubbleUser className2="mb-2">
                What do you know about me?
              </SimpleChatBubbleUser>
              {personalInfo.map((info, index) => (
                <div
                  key={index}
                  className="mr-2 flex gap-1 rounded-xl bg-zinc-700 px-2 py-1.5 text-xs sm:mr-4 sm:gap-2 sm:rounded-2xl sm:px-3 sm:py-2 sm:text-sm lg:mr-7 lg:px-4 lg:text-base"
                >
                  <AiBrain01Icon className="relative top-0.5 h-3 w-3 flex-shrink-0 text-zinc-400 sm:h-4 sm:w-4 lg:h-5 lg:w-5" />
                  <div className="w-full">{info}</div>
                </div>
              ))}
            </div>
          </BentoItem>

          <BentoItem
            title="Build a Knowledge Graph"
            description="Builds intelligent bridges between your scattered memories"
            childrenClassName="p-0 overflow-hidden"
          >
            <MemoryGraphDemo />
          </BentoItem>
        </div>
      </div>
    </div>
  );
}
