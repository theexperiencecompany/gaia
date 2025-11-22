import { VelocityScroll } from "./scroll-based-velocity";

export default function ScrollingText() {
  return (
    <VelocityScroll
      className="font-display text-center text-4xl font-bold tracking-[-0.02em] text-black drop-shadow-xs md:text-7xl md:leading-[5rem] dark:text-white"
      text="Personalised Just for You  &nbsp;"
    />
  );
}
