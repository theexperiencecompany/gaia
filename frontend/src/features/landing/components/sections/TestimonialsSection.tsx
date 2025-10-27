import Image from "next/image";

import { Marquee } from "@/components/ui/marquee";
import { cn } from "@/lib/utils";

import { testimonials as initial } from "../../data/testimonials";
import LargeHeader from "../shared/LargeHeader";
import SectionLayout from "../shared/SectionLayout";

const testimonials = initial.sort(() => Math.random() - 0.5);
const firstRow = testimonials.slice(0, testimonials.length / 2);
const secondRow = testimonials.slice(testimonials.length / 2);

const TestimonialCard = ({
  img,
  name,
  body,
  role,
}: {
  img: string;
  name: string;
  body: string;
  role: string;
}) => {
  return (
    <figure
      className={cn(
        "relative h-full w-100 overflow-hidden rounded-3xl transition-all",
        "bg-zinc-900 hover:bg-zinc-800",
        "p-4",
      )}
    >
      <div className="flex flex-row items-center gap-2">
        <Image
          className="aspect-square rounded-full bg-white"
          width="35"
          height="35"
          alt={`${name} avatar`}
          src={img}
        />
        <div className="flex flex-col">
          <figcaption className="text-sm font-normal text-white sm:text-base">
            {name}
          </figcaption>
          <p className="text-xs text-zinc-500 sm:text-sm">{role}</p>
        </div>
      </div>
      <blockquote className="mt-2 max-h-26 overflow-y-auto text-sm leading-relaxed text-zinc-300">
        {body}
      </blockquote>
    </figure>
  );
};

export default function TestimonialsSection() {
  return (
    <SectionLayout className="relative flex h-screen items-center px-4 sm:px-6 lg:px-8">
      <div className="flex w-full max-w-7xl flex-col items-center justify-center">
        <LargeHeader
          chipText="Wall of Love"
          headingText="Loved by thousands of users"
          subHeadingText="See what people are saying about their experience with GAIA"
          centered
        />

        <div className="relative mt-8 flex w-full flex-col items-center justify-center overflow-hidden sm:mt-12 md:mt-16">
          <Marquee
            pauseOnHover
            className="[--duration:30s] sm:[--duration:25s]"
          >
            {firstRow.map((testimonial) => (
              <TestimonialCard key={testimonial.name} {...testimonial} />
            ))}
          </Marquee>
          <Marquee
            reverse
            pauseOnHover
            className="[--duration:35s] sm:[--duration:30s]"
          >
            {secondRow.map((testimonial) => (
              <TestimonialCard key={testimonial.name} {...testimonial} />
            ))}
          </Marquee>

          {/* Gradient overlays */}
          <div className="pointer-events-none absolute inset-y-0 left-0 w-1/6 bg-gradient-to-r from-background to-transparent sm:w-1/5" />
          <div className="pointer-events-none absolute inset-y-0 right-0 w-1/6 bg-gradient-to-l from-background to-transparent sm:w-1/5" />
        </div>
      </div>
    </SectionLayout>
  );
}
