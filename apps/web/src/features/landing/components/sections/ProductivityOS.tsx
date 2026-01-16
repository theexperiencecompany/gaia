// import { Chip } from "@heroui/react";
// import Image from "next/image";
// import { useEffect, useState } from "react";
import { ContentSection } from "../shared/ContentSection";
import LargeHeader from "../shared/LargeHeader";

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
//     src: "/images/screenshots/todos.png",
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

export default function ProductivityOS() {
  // const [selected, setSelected] = useState(imageOptions[2]);

  // Preload all images
  // useEffect(() => {
  //   imageOptions.forEach((img) => {
  //     const preload = new window.Image();
  //     preload.src = img.src;
  //   });
  // }, []);

  return (
    <div className="min-h-screen flex items-center justify-start flex-col gap-16 max-w-7xl mx-auto z-[1] relative">
      <LargeHeader
        chipText="The future of personal assistants"
        headingText="Your Productivity Operating System"
        subHeadingText="One system to manage your tasks, time, and information."
        centered
      />

      <div className="grid w-full gap-6 grid-cols-2 sm:gap-8 lg:gap-10 relative z-[1]">
        <div className="row-span-3 space-y-7">
          <ContentSection
            title="A future where everyone has a real personal assistant"
            description="We’re building toward a world where everyone has an assistant that’s actually by their side. Not an app you open, not a chatbot you occasionally check, but something that’s always present. On your laptop. On your phone. In your browser. Eventually in smart glasses."
          />
          <ContentSection
            description=" An assistant that sees what you’re doing, understands the context
          instantly, and can take over the moment you need it. It should be able
          to control your applications, move through interfaces, handle work
          across your entire stack, and take action with the same confidence as
          a human. The future we see is simple."
          />
          <ContentSection description="Every person has a reliable, persistent assistant that runs in the background and clears the path for real work. An assistant that doesn’t wait for commands, but helps you the second you need it. That’s the world we’re building with GAIA." />
        </div>
        <ContentSection
          title="The central layer for all your work"
          description="Most people work across scattered apps. Email in one place. Tasks in
          another. Notes somewhere else. Calendar somewhere else. None of these
          tools talk to each other, so you end up doing the glue work yourself.
          GAIA replaces that glue. It becomes the single system that tracks what
          needs to happen, when it needs to happen, and what context it depends
          on."
        />
        <ContentSection
          title="Accessible anywhere you work"
          description="A system like this only works if you can reach it instantly. Our long term plan is a full accessibility layer: web app, desktop app, phone calls, mobile app, browser extension, CLI, Discord & Slack bots and more. You should be able to call your assistant from whatever environment you’re already in. We’re starting with the web so we can ship fast and learn quickly, then expanding into every other surface you use."
        />
        <ContentSection
          title="A unified productivity hub"
          description="One system for your todos, emails, calendar, goals and more, all driven by an assistant that actually knows what’s going on. GAIA keeps your work in one place, understands the context, and handles the coordination for you. The interface is fast and command-driven, inspired by tools like Linear and Superhuman, so you can move quickly without fighting your workflow."
        />
      </div>
      {/* 
      <div className="flex flex-col justify-center gap-6 items-center">
        <div className="flex gap-3">
          {imageOptions.map((option) => (
            <Chip
              key={option.name}
              onClick={() => setSelected(option)}
              color={selected.name === option.name ? "primary" : "default"}
              className="cursor-pointer"
              variant={"solid"}
              size="lg"
            >
              {option.name}
            </Chip>
          ))}
        </div>

        <Image
          width={1920}
          height={1080}
          className="w-full rounded-3xl border-2 border-border-surface-800 min-w-full"
          src={selected.src}
          alt={selected.name}
          priority
        />
      </div> */}
    </div>
  );
}
