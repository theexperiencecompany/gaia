"use client";

import { gsap } from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import Image from "next/image";
import { useEffect, useRef } from "react";

gsap.registerPlugin(ScrollTrigger);

export default function ChaoticWorkspaceSection() {
  const sectionRef = useRef<HTMLElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const iconsRef = useRef<HTMLDivElement[]>([]);

  useEffect(() => {
    if (!sectionRef.current || !textRef.current) return;

    const ctx = gsap.context(() => {
      // Text animation - fade in first
      gsap.fromTo(
        textRef.current,
        {
          opacity: 0,
          y: 50,
        },
        {
          opacity: 1,
          y: 0,
          duration: 1,
          ease: "power2.out",
          scrollTrigger: {
            trigger: sectionRef.current,
            start: "top 80%",
            end: "top 20%",
            toggleActions: "play none none reverse",
          },
        },
      );

      // Icons animation - simple scale up from center
      gsap.fromTo(
        iconsRef.current,
        {
          scale: 0,
          opacity: 0,
        },
        {
          scale: 1,
          rotation: (i) => {
            const rotations = [
              12, 6, -12, 45, 45, -12, -45, -45, 12, -12, 12, 12,
            ];
            return rotations[i] || 0;
          },
          opacity: 1,
          duration: 0.5,
          ease: "back.out(1.7)",
          stagger: {
            amount: 0.4,
            from: "random",
          },
          scrollTrigger: {
            trigger: sectionRef.current,
            start: "top 60%",
            end: "bottom 40%",
            toggleActions: "play none none reverse",
          },
        },
      );
    }, sectionRef);

    return () => ctx.revert();
  }, []);

  const addToRefs = (el: HTMLDivElement | null) => {
    if (el && !iconsRef.current.includes(el)) {
      iconsRef.current.push(el);
    }
  };

  return (
    <section
      ref={sectionRef}
      className="relative flex min-h-screen items-center justify-center overflow-hidden"
    >
      {/* Central Text */}
      <div ref={textRef} className="relative z-10 text-center">
        <h2 className="font-serif text-8xl font-light text-white">
          The current way we
          <br />
          work is
          <span className="pl-5 text-primary">chaotic</span>.
        </h2>
      </div>

      {/* Floating Icons with Even Spacing */}
      {/* Top Row */}
      {/* Google Calendar - Top Left */}
      <div
        ref={addToRefs}
        className="absolute top-24 left-1/3 -translate-x-1/2 transform"
      >
        <div className="relative">
          <Image
            src="/images/icons/googlecalendar.webp"
            alt="Google Calendar"
            width={60}
            height={60}
            className="rounded-xl"
          />
          <div className="absolute -top-2 -right-2 rounded-full bg-red-500 px-2 py-1 text-sm font-bold text-white">
            99+
          </div>
        </div>
      </div>

      {/* Slack - Top Center */}
      <div
        ref={addToRefs}
        className="absolute top-16 left-1/2 -translate-x-1/2 transform"
      >
        <div className="relative">
          <Image
            src="/images/icons/slack.svg"
            alt="Slack"
            width={55}
            height={55}
            className="rounded-xl"
          />
          <div className="absolute -top-2 -right-2 rounded-full bg-green-500 px-2 py-1 text-sm font-bold text-white">
            1M+
          </div>
        </div>
      </div>

      {/* Notion - Top Right */}
      <div
        ref={addToRefs}
        className="absolute top-24 right-1/3 translate-x-1/2 transform"
      >
        <div className="relative">
          <Image
            src="/images/icons/notion.webp"
            alt="Notion"
            width={58}
            height={58}
            className="rounded-xl"
          />
          <div className="absolute -top-2 -right-2 rounded-full bg-blue-500 px-2 py-1 text-sm font-bold text-white">
            Join
          </div>
        </div>
      </div>

      {/* Middle Row */}
      {/* LinkedIn - Far Left */}
      <div
        ref={addToRefs}
        className="absolute top-1/2 left-20 -translate-y-1/2 transform"
      >
        <Image
          src="/images/icons/linkedin.svg"
          alt="LinkedIn"
          width={50}
          height={50}
          className="rounded-xl"
        />
      </div>

      {/* Gmail - Left Side */}
      <div
        ref={addToRefs}
        className="absolute top-50 left-60 -translate-x-1/2 -translate-y-1/2 transform"
      >
        <div className="relative">
          <Image
            src="/images/icons/gmail.svg"
            alt="Gmail"
            width={65}
            height={65}
            className="rounded-xl"
          />
          <div className="absolute -top-2 -right-2 rounded-full bg-red-600 px-2 py-1 text-sm font-bold text-white">
            420
          </div>
        </div>
      </div>

      {/* GitHub - Right Side */}
      <div
        ref={addToRefs}
        className="absolute right-60 bottom-40 translate-x-1/2 -translate-y-1/2 transform"
      >
        <div className="relative">
          <Image
            src="/images/icons/github3d.webp"
            alt="GitHub"
            width={58}
            height={58}
            className="rounded-xl"
          />
        </div>
      </div>

      {/* Figma - Far Right */}
      <div
        ref={addToRefs}
        className="absolute top-1/2 right-20 -translate-y-1/2 transform"
      >
        <Image
          src="/images/icons/figma.svg"
          alt="Figma"
          width={50}
          height={50}
          className="rounded-xl"
        />
      </div>

      {/* Bottom Row */}
      {/* Google Sheets - Bottom Left */}
      <div
        ref={addToRefs}
        className="absolute bottom-24 left-1/3 -translate-x-1/2 transform"
      >
        <Image
          src="/images/icons/google_sheets.webp"
          alt="Google Sheets"
          width={50}
          height={50}
          className="rounded-xl"
        />
      </div>

      {/* Google Docs - Bottom Center */}
      <div
        ref={addToRefs}
        className="absolute bottom-16 left-1/2 -translate-x-1/2 transform"
      >
        <div className="relative">
          <Image
            src="/images/icons/google_docs.webp"
            alt="Google Docs"
            width={55}
            height={55}
            className="rounded-xl"
          />
          <div className="absolute -right-2 -bottom-2 rounded-full bg-gray-700 px-2 py-1 text-xs font-bold text-white">
            Offline
          </div>
        </div>
      </div>

      {/* Trello - Bottom Right */}
      <div
        ref={addToRefs}
        className="absolute right-1/3 bottom-24 translate-x-1/2 transform"
      >
        <div className="relative">
          <Image
            src="/images/icons/trello.svg"
            alt="Trello"
            width={55}
            height={55}
            className="rounded-xl"
          />
          <div className="absolute -top-2 -right-2 rounded-full bg-purple-500 px-2 py-1 text-sm font-bold text-white">
            100
          </div>
        </div>
      </div>

      {/* Additional Icons for More Chaos */}
      {/* WhatsApp - Bottom Left Corner */}
      <div ref={addToRefs} className="absolute bottom-32 left-24 transform">
        <div className="relative">
          <Image
            src="/images/icons/whatsapp.webp"
            alt="WhatsApp"
            width={60}
            height={60}
            className="rounded-xl"
          />
          <div className="absolute -top-2 -right-2 rounded-full bg-red-500 px-2 py-1 text-sm font-bold text-white">
            99+
          </div>
        </div>
      </div>

      {/* Todoist - Top Right Corner */}
      <div ref={addToRefs} className="absolute top-32 right-24 transform">
        <Image
          src="/images/icons/todoist.svg"
          alt="Todoist"
          width={50}
          height={50}
          className="rounded-xl"
        />
      </div>
    </section>
  );
}
