import Image from "next/image";
import { Suspense } from "react";
import ReactMarkdown from "react-markdown";

import { AuthorTooltip } from "@/features/blog/components/AuthorTooltip";
import { generateAboutPageSchema, generatePageMetadata } from "@/lib/seo";
import type { AboutData, Author } from "@/types/api/aboutApiTypes";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";

export default async function About() {
  const aboutPageSchema = generateAboutPageSchema();
  const aboutData: AboutData | null = {
    content:
      "Hey\n\nWe're building GAIA because we've always wanted a personal assistant that actually does things for us, not just answer questions or pretend to help. The truth is, tools like Siri, Alexa, and even ChatGPT are helpful in small ways, but they are not real assistants.\n\nThey don’t remember you, they don’t handle your work, and they don’t make your life easier the way a human would.\n\nGAIA is our attempt to change that.\n\nWe’re building GAIA, which stands for General-purpose AI Assistant, as a personal assistant that’s always by your side. It connects to your digital life, learns how you work, and starts taking care of automating the boring stuff such as emails, meetings, scheduling, reminders, calls, your goals, and your habits so you can focus on what actually matters.\n\n Our end goal is for GAIA to be on every device, for every person in the world. We believe that building something that powerful starts by focusing on productivity and helping people get real work done today.\n\nThe possibilities of an assistant that knows everything you do, is deeply integrated with your life and tools, has endless memory about your life, and stays by your side are endless.\n\nPrivacy and security are our top priorities. We will never sell your data or use it to train models. We are building GAIA because we love creating tools that make a difference, and we would do it even if we weren’t being paid.\n\nWe’re also open source because we want to be fully transparent. Being open source not only allows the community to see exactly how GAIA works, it also reinforces privacy by design, everyone can verify that data is handled responsibly. As founders, we’ve had amazing experiences with the open-source community. It’s incredible how people come together to build something bigger than themselves, and we want to give back to that same spirit.\n\nWe envision a world where everyone has their own personal AI assistant like Jarvis from Iron Man. Not just a tool, but a proactive, intelligent presence that knows you, helps you, and works with you. That is the kind of future we want to help build.\n\nWe’re a really small team building fast, learning fast, and trying to solve one of the hardest and most exciting problems in tech today.\n\nWe’re just getting started, and there’s a lot more to come. We hope you find GAIA not just useful, but a little magical in how it makes your life easier.\n\nWe appreciate every bit of support. Thanks for being here.",
    authors: [
      {
        name: "Aryan Randeriya",
        avatar: "https://github.com/aryanranderiya.png",
        role: "Founder & CEO",
        linkedin: "https://www.linkedin.com/in/aryanranderiya/",
        twitter: "https://twitter.com/aryanranderiya",
        github: "https://github.com/aryanranderiya",
      },
      {
        name: "Dhruv Maradiya",
        avatar: "https://github.com/dhruv-maradiya.png",
        role: "Founder & CTO",
        linkedin: "https://www.linkedin.com/in/dhruvmaradiya/",
        twitter: "https://twitter.com/dhruvmaradiya",
        github: "https://github.com/dhruv-maradiya",
      },
    ],
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(aboutPageSchema) }}
      />
      <div className="flex min-h-screen w-screen justify-center bg-black px-6 py-28">
        <div className="fixed top-0 left-0 z-[0] flex h-screen w-full items-center justify-center opacity-5">
          <Image
            src="/images/logos/logo.webp"
            alt="GAIA Logo"
            className="scale-110 object-contain grayscale"
            fill
          />
        </div>

        <div className="relative max-w-(--breakpoint-lg) space-y-8">
          <Suspense fallback={<div>Loading...</div>}>
            <div className="flex w-full justify-center">
              <Image
                src="/images/logos/logo.webp"
                alt="GAIA Logo"
                width={80}
                height={80}
              />
            </div>
            <div className="prose prose-zinc dark:prose-invert max-w-2xl">
              <ReactMarkdown
                components={{
                  h1: ({ children }) => (
                    <h1 className="mb-6 text-center text-3xl font-bold">
                      {children}
                    </h1>
                  ),
                  h2: ({ children }) => (
                    <h2 className="mt-8 mb-4 text-2xl font-semibold">
                      {children}
                    </h2>
                  ),
                  h3: ({ children }) => (
                    <h3 className="mt-6 mb-3 text-xl font-semibold">
                      {children}
                    </h3>
                  ),
                  p: ({ children }) => (
                    <p className="mb-4 text-left text-lg font-light tracking-tight text-foreground-600">
                      {children}
                    </p>
                  ),
                  ul: ({ children }) => (
                    <ul className="mb-4 ml-6 list-disc space-y-2">
                      {children}
                    </ul>
                  ),
                  li: ({ children }) => (
                    <li className="text-foreground-600">{children}</li>
                  ),
                  strong: ({ children }) => (
                    <strong className="font-semibold text-foreground">
                      {children}
                    </strong>
                  ),
                  a: ({ children }) => (
                    <a className="cursor-pointer text-primary hover:underline">
                      {children}
                    </a>
                  ),
                }}
              >
                {aboutData.content}
              </ReactMarkdown>
            </div>
          </Suspense>

          <div className="flex items-center gap-3">
            <div className="flex items-center -space-x-2">
              {aboutData.authors.map((author: Author) => (
                <AuthorTooltip
                  key={author.name}
                  author={author}
                  avatarSize="md"
                  avatarClassName="h-10 w-10 cursor-help border-2 border-background"
                />
              ))}
            </div>
            <div className="text-foreground-500">— The Founders</div>
          </div>
          <div className="flex w-full justify-start">
            <GetStartedButton text="Get Started" />
          </div>
        </div>
      </div>
    </>
  );
}
