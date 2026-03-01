"use client";

import { Button } from "@heroui/button";
import { ArrowRight02Icon, RedoIcon } from "@icons";
import { m, useReducedMotion } from "motion/react";
import Image from "next/image";
import type React from "react";

interface DemoNavControlsProps {
  phaseIndex: number;
  phaseCount: number;
  onPrev: () => void;
  onNext: () => void;
  onRestart: () => void;
}

export function DemoNavControls({
  phaseIndex,
  phaseCount,
  onPrev,
  onNext,
  onRestart,
}: DemoNavControlsProps) {
  return (
    <div className="flex w-full items-center justify-between">
      <div className="flex items-center gap-1.5">
        <Button
          isIconOnly
          variant="flat"
          size="sm"
          title="Previous phase"
          aria-label="Previous phase"
          onPress={onPrev}
          isDisabled={phaseIndex <= 0}
          className="rounded-full"
        >
          <ArrowRight02Icon width={18} height={18} className="rotate-180" />
        </Button>
        <Button
          isIconOnly
          variant="flat"
          size="sm"
          title="Next phase"
          aria-label="Next phase"
          onPress={onNext}
          isDisabled={phaseIndex >= phaseCount - 1}
          className="rounded-full"
        >
          <ArrowRight02Icon width={18} height={18} />
        </Button>
      </div>
      <Button
        isIconOnly
        variant="flat"
        size="sm"
        title="Restart demo"
        aria-label="Restart demo"
        onPress={onRestart}
        className="rounded-full"
      >
        <RedoIcon width={18} height={18} />
      </Button>
    </div>
  );
}

interface DemoBackgroundProps {
  ease: [number, number, number, number];
  children: React.ReactNode;
}

export function DemoBackground({ ease, children }: DemoBackgroundProps) {
  const prefersReduced = useReducedMotion();

  return (
    <m.div
      initial={{ opacity: 0, y: 20, scale: 0.97 }}
      whileInView={{ opacity: 1, y: 0, scale: 1 }}
      viewport={{ once: true }}
      transition={{ duration: 0.5, ease }}
      className="relative flex h-[70vh] w-full items-center justify-center overflow-hidden rounded-2xl"
    >
      <m.div
        className="absolute inset-0"
        animate={prefersReduced ? {} : { scale: [1, 1.1, 1] }}
        transition={{
          duration: 10,
          repeat: Number.POSITIVE_INFINITY,
          ease: "linear",
        }}
      >
        <Image
          src="/images/wallpapers/mesh_gradient_1.webp"
          alt="Mesh gradient background"
          width={1920}
          height={1080}
          sizes="100vw"
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            position: "absolute",
            inset: 0,
          }}
          className="object-cover"
          priority
        />
      </m.div>
      <div className="absolute inset-0 bg-black/10 backdrop-blur-sm" />
      {children}
    </m.div>
  );
}
