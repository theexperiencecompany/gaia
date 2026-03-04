import { m, useInView } from "motion/react";
import type { ReactNode } from "react";
import { useRef } from "react";
import IntegrationStrip from "./IntegrationStrip";

const ease = [0.22, 1, 0.36, 1] as const;

export default function SectionHeader({
  label,
  headline,
  description,
  integrations,
  labelIcon,
}: {
  label: string;
  headline: ReactNode;
  description: string;
  integrations?: { id: string; label: string }[];
  labelIcon?: ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const inView = useInView(ref, { once: true, amount: 0.15 });

  return (
    <div ref={ref} className="flex flex-col items-center text-center">
      <m.span
        initial={{ opacity: 0, y: 8 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.5, ease }}
        className="mb-4 flex items-center gap-1.5 text-xs font-medium uppercase tracking-widest text-primary"
      >
        {labelIcon}
        {label}
      </m.span>
      <m.h2
        initial={{ opacity: 0, y: 16 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6, ease, delay: 0.08 }}
        className="font-serif mb-5 max-w-5xl text-5xl font-normal text-white sm:text-5xl"
      >
        {headline}
      </m.h2>
      <m.p
        initial={{ opacity: 0, y: 16 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6, ease, delay: 0.16 }}
        className="mb-4 max-w-2xl text-lg font-light leading-relaxed text-zinc-400"
      >
        {description}
      </m.p>
      {integrations && (
        <m.div
          initial={{ opacity: 0 }}
          animate={inView ? { opacity: 1 } : {}}
          transition={{ duration: 0.5, ease, delay: 0.24 }}
          className="mb-10"
        >
          <IntegrationStrip integrations={integrations} />
        </m.div>
      )}
      {!integrations && <div className="mb-10" />}
    </div>
  );
}
