"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib";

import type { Heading } from "../utils/parseHeadings";

interface TableOfContentsProps {
  headings: Heading[];
}

export default function TableOfContents({ headings }: TableOfContentsProps) {
  const [activeId, setActiveId] = useState<string>("");

  useEffect(() => {
    const onScroll = () => {
      const scrollY = window.scrollY + 140;

      let currentId = "";
      for (const { id } of headings) {
        const el = document.getElementById(id);
        if (el && el.offsetTop <= scrollY) {
          currentId = id;
        }
      }
      setActiveId(currentId);
    };

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener("scroll", onScroll);
  }, [headings]);

  if (headings.length === 0) return null;

  return (
    <nav aria-label="Table of contents" className="sticky top-28 w-56">
      <p className="mb-3 text-[11px] font-medium uppercase tracking-widest text-zinc-600">
        On this page
      </p>
      <ul className="space-y-0.5">
        {headings.map((heading) => {
          const isActive = activeId === heading.id;
          return (
            <li key={heading.id}>
              <a
                href={`#${heading.id}`}
                onClick={(e) => {
                  e.preventDefault();
                  const el = document.getElementById(heading.id);
                  if (el) {
                    const top =
                      el.getBoundingClientRect().top + window.scrollY - 100;
                    window.scrollTo({ top, behavior: "smooth" });
                  }
                }}
                className={cn(
                  "block border-l py-1 text-[13px] leading-snug transition-colors duration-150",
                  heading.level === 1
                    ? "pl-3"
                    : heading.level === 2
                      ? "pl-3"
                      : "pl-6",
                  isActive
                    ? "border-l-zinc-400 text-zinc-100"
                    : "border-l-transparent text-zinc-500 hover:border-l-zinc-700 hover:text-zinc-300",
                )}
              >
                {heading.text}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
