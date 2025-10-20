import { Chip } from "@heroui/chip";
import { DotLottieReact } from "@lottiefiles/dotlottie-react";
import Image from "next/image";

import { BentoItem } from "./TodosBentoContent";

const triggers = [
  {
    icon: "/images/icons/slack.svg",
    title: "Slack",
    description: "Trigger on Slack mention",
  },
  {
    icon: "/images/icons/googlecalendar.webp",
    title: "Calendar",
    description: "Trigger on calendar event",
  },

  {
    icon: "/images/icons/gmail.svg",
    title: "Gmail",
    description: "Trigger on new email",
  },
];

export default function WorkflowSection() {
  return (
    <div className="mx-auto flex h-screen w-full max-w-7xl flex-col justify-center p-4 px-4 sm:p-6 sm:px-6 lg:p-7 lg:px-8">
      <div className="mb-2 text-xl font-light text-primary sm:text-2xl">
        Your Daily Life, Automated
      </div>
      <div className="mb-4 text-3xl font-normal sm:mb-5 sm:text-4xl lg:text-5xl">
        Simple workflows to eliminate repetitive tasks
      </div>

      <div className="grid w-full max-w-7xl grid-cols-1 grid-rows-1 justify-between gap-4 sm:gap-6 lg:grid-cols-3 lg:gap-7">
        <BentoItem
          title="Smart Triggers"
          description="Set conditions once, automate actions forever."
        >
          <div className="flex w-full flex-col items-center justify-center gap-2 px-1 sm:gap-3">
            {triggers.map((trigger, index) => (
              <div
                key={index}
                className={`flex w-full items-center gap-2 rounded-xl bg-zinc-800 p-2 sm:gap-3 sm:rounded-2xl sm:p-3`}
              >
                <Image
                  src={trigger.icon}
                  alt={trigger.title}
                  className="h-6 w-6 sm:h-8 sm:w-8"
                  width={32}
                  height={32}
                />
                <div className="flex flex-col">
                  <span className="text-sm font-medium text-white sm:text-base">
                    {trigger.title}
                  </span>
                  <span className="text-xs text-zinc-300 sm:text-sm">
                    {trigger.description}
                  </span>
                </div>
              </div>
            ))}
            <Chip
              color="primary"
              variant="flat"
              className="mt-1 text-xs text-primary sm:mt-2 sm:text-sm"
            >
              Automatically run workflows on triggers
            </Chip>
          </div>
        </BentoItem>
        <BentoItem
          title="Proactive by Nature"
          description="GAIA acts before you ask, preparing what you need when you need it."
          childrenClassName="p-0!"
        >
          <DotLottieReact
            src="/animations/proactive.lottie"
            loop
            autoplay
            speed={0.5}
            // playOnHover
          />
        </BentoItem>
        <BentoItem
          title="Seamless Orchestration"
          description="Makes all your apps work together like a single tool, through a unified interface."
        >
          <DotLottieReact
            src="/animations/seamless.json"
            loop
            autoplay
            speed={0.7}
            playOnHover
          />
        </BentoItem>{" "}
      </div>
    </div>
  );
}
