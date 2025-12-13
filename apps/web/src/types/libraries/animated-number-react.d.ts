declare module "animated-number-react" {
  export interface AnimatedNumberProps {
    value: string | number | undefined;
    className?: string;
    duration?: number;
    formatValue?: (n: number) => string;
  }

  const AnimatedNumber: React.ComponentType<AnimatedNumberProps>;
  export default AnimatedNumber;
}
