"use client";

import { motion, useAnimation, Variants } from "framer-motion";
import { useEffect } from "react";
import { useInView } from "react-intersection-observer";

import { cn } from "@/lib/utils";

interface WordPullUpProps {
  words: string;
  delayMultiple?: number;
  wrapperFramerProps?: Variants;
  framerProps?: Variants;
  className?: string;
}

export default function WordPullUp({
  words,
  wrapperFramerProps = {
    hidden: { opacity: 0 },
    show: {
      opacity: 1,
      transition: {
        staggerChildren: 0.2,
      },
    },
  },
  framerProps = {
    hidden: { y: 20, opacity: 0 },
    show: { y: 0, opacity: 1 },
  },
  className,
}: WordPullUpProps) {
  const controls = useAnimation();
  const { ref, inView } = useInView({ triggerOnce: true, threshold: 0.1 });

  useEffect(() => {
    if (inView) {
      controls.start("show");
    }
  }, [inView, controls]);

  return (
    <motion.h1
      ref={ref}
      animate={controls}
      className={cn(
        "font-display text-center text-4xl leading-[5rem] font-bold tracking-[-0.02em] drop-shadow-lg",
        className,
      )}
      initial="hidden"
      variants={wrapperFramerProps}
    >
      {words.split(" ").map((word, i) => (
        <motion.span
          key={i}
          style={{ display: "inline-block", paddingRight: "8px" }}
          variants={framerProps}
        >
          {word === "" ? <span>&nbsp;</span> : word}
        </motion.span>
      ))}
    </motion.h1>
  );
}
