import Image from "next/image";
import { Suspense } from "react";
import ReactMarkdown from "react-markdown";

import JsonLd from "@/components/seo/JsonLd";
import { AuthorTooltip } from "@/features/blog/components/AuthorTooltip";
import GetStartedButton from "@/features/landing/components/shared/GetStartedButton";
import { generateAboutPageSchema } from "@/lib/seo";
import type { AboutData, Author } from "@/types/api/aboutApiTypes";

export default async function About() {
  const aboutPageSchema = generateAboutPageSchema();
  const aboutData: AboutData | null = {
    content:
      "## Every Human Deserves a Jarvis\n\nClose your eyes and imagine: An assistant who knows your work, your patterns, your preferences. Who reads every email before you do and surfaces only what matters. Who schedules your day optimally, drafts your responses, researches before you ask, and remembers everything you've ever worked on. Who doesn't wait for commands but anticipates your needs. Who gets smarter the longer they work with you.\n\nThis is not science fiction. This is GAIA.\n\nOur vision is simple but audacious: every person in the world should have their own personal AI assistant like Jarvis from Iron Man. Not just a tool, but a proactive, intelligent presence that knows you, helps you, and works with you. Not in fifty years, not for the privileged few, but now, for everyone.\n\n## The Problem We're Solving\n\nWe all drown in tools. Gmail, Calendar, Todos, Docs, Slack, Linear, WhatsApp - the list keeps growing. Every person has a different stack, but the problem is universal: our days are consumed by small, repetitive actions that feel necessary but aren't real work.\n\nEvery calendar event you create is a few minutes gone. Every email you draft, every todo you try to complete, every message you read that turns out to be noise - it all adds up. Most of this isn't meaningful work. It's maintenance. Digital housekeeping just to keep everything structured and prevent chaos.\n\nResearch shows knowledge workers spend nearly 40% of their time on email, meetings, and task management. That's 16 hours per week. 832 hours per year. Nearly 20 full work weeks doing digital maintenance instead of actual creative or strategic work.\n\nEach task feels small in isolation, but together they are mentally crushing. They pile up day after day, quietly draining focus and motivation. Over time, inboxes get cluttered, todo lists rot, messages pile up, and important things slip through the cracks. This slow accumulation is what pushes people into jobs they hate, doing things they don't enjoy - not because the work itself is meaningless, but because their mental bandwidth is constantly consumed by noise.\n\nThat's exactly how this started for us. We missed a time-sensitive email because everything looked equally urgent and we were already mentally exhausted. A single missed email cascaded into missed opportunities, frustrated partners, and the realization that we had become servants to our tools rather than masters of them.\n\nExisting tools don't solve this. Siri sets timers. Alexa plays music. ChatGPT answers questions brilliantly but can't act on your behalf. These are not assistants - they're sophisticated search boxes with voice interfaces. Even automation tools like Zapier are powerful, but rigid and technical. They require you to think like a programmer, not like someone who just wants things done.\n\nA real assistant doesn't wait for commands. They understand what you need before you ask. They manage complexity so you don't have to think about it. They learn from every interaction and get better over time. They have agency, memory, and initiative.\n\nThat's what we're building.\n\n## Why Now\n\nAI capabilities have reached an inflection point. Large language models can understand context, generate human-quality text, reason through problems, and converse naturally. The tools to integrate with every digital service exist. Knowledge graphs can store and connect infinite amounts of information.\n\nThe technology is ready. What's been missing is the vision to combine these capabilities into a true assistant, and the commitment to do it right - with privacy, transparency, and the user in control.\n\nThe world has never been more complex, more interconnected, or more demanding of our attention. The cognitive load on knowledge workers has never been higher. We need this now more than ever. The question isn't whether personal AI assistants will exist - it's who builds them and how.\n\n## Our Approach: Built Different\n\nWe're building GAIA - General-purpose AI Assistant - as a personal assistant that's always by your side. It connects to your entire digital life, learns how you work, and quietly handles the boring, repetitive work so you can focus on what actually matters.\n\n**Deep Integration**: GAIA connects with your email, calendar, todos, communication tools, and knowledge bases. It sees your entire digital life the way a human assistant would.\n\n**Persistent Memory**: A graph-based knowledge system that connects tasks to projects, meetings to documents, people to topics. GAIA remembers everything and understands how it all relates. The longer you work with GAIA, the smarter it gets.\n\n**Proactive Intelligence**: You shouldn't have to ask. GAIA monitors your upcoming deadlines, watches for important emails, identifies tasks that need attention, and acts before you think to prompt it. This is the core difference - agency, not reactivity.\n\n**Intelligent Action**: Don't just get answers - get work done. GAIA can send emails, schedule meetings, create documents, triage your inbox, conduct research, and execute multi-step workflows automatically.\n\n**Privacy by Architecture**: Privacy isn't a feature - it's our foundation. Your assistant knows everything about you: your work, your habits, your communications, your goals. That level of access requires absolute trust.\n\nThis is why GAIA is open source. Every line of code is auditable. This is why it's self-hostable. Your data lives where you want it. This is why we will never sell your information or train models on it. We're not building an advertising platform disguised as an assistant. We're building an assistant you can trust with your digital life because we've designed it to be trustworthy from the ground up.\n\nBeing open source also reinforces innovation. We've had incredible experiences with the open-source community. It's extraordinary how people come together to build something bigger than themselves. We want to give back to that same spirit and invite the world to help us build the future of personal AI.\n\n## The Journey Ahead\n\nWe're focusing first on productivity and knowledge workers - people who value their time intensely and do meaningful creative or strategic work. We believe this is how you build something that scales to everyone: start with the hardest problems, solve them elegantly, then expand.\n\nOur end goal is for GAIA to be on every device, for every person in the world. Mobile, desktop, web - everywhere you are, GAIA is there. The possibilities of an assistant that knows everything you do, is deeply integrated with your life and tools, has endless memory, and stays by your side are limitless.\n\nWe're a small team building fast, learning every day, and working on one of the hardest and most exciting challenges in technology today. We're just getting started, and there's so much more to come.\n\nThis is not just a product. This is the beginning of a fundamental shift in how humans interact with technology. We're building a world where you don't serve your tools - they serve you. Where your digital life is managed intelligently and proactively. Where you reclaim your time, your focus, and your mental energy for the work that actually matters.\n\nIf you believe everyone deserves a Jarvis, join us. Use GAIA. Contribute code. Share feedback. Tell others. Every conversation, every contribution, every person who finds their time reclaimed brings us closer to the world we're building.\n\nThe future doesn't wait. Let's build it together.",
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
      <JsonLd data={aboutPageSchema} />
      <div className="flex min-h-screen w-screen justify-center bg-black px-6 py-28">
        <div className="fixed top-0 left-0 z-0 flex h-screen w-full items-center justify-center opacity-5">
          <Image
            src="/images/logos/logo.webp"
            alt="GAIA Logo"
            className="scale-110 object-contain grayscale"
            fill
          />
        </div>

        <div className="relative max-w-(--breakpoint-lg) space-y-8">
          <Suspense fallback={<div>Loading...</div>}>
            <h1 className="sr-only">About GAIA</h1>
            <div className="flex w-full justify-center gap-10">
              <Image
                src="/images/logos/logo.webp"
                alt="GAIA Logo"
                width={80}
                height={80}
              />

              <Image
                src="/images/logos/experience_logo.svg"
                alt="The Experience Company Logo"
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
                  a: ({ href, children }) => (
                    <a
                      className="cursor-pointer text-primary hover:underline"
                      href={href}
                    >
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
            <div className="text-foreground-500">
              — Founders, The Experience Company
            </div>
          </div>
          <div className="flex w-full justify-start">
            <GetStartedButton text="Sign Up" />
          </div>
        </div>
      </div>
    </>
  );
}
