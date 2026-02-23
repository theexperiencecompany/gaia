import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { Text as RNText } from "react-native";
import { cn } from "@/lib/utils";

const textVariants = cva("text-foreground text-base", {
  variants: {
    variant: {
      default: "",
      h1: "text-4xl font-extrabold tracking-tight text-center",
      h2: "text-3xl font-semibold tracking-tight border-b border-border pb-2",
      h3: "text-2xl font-semibold tracking-tight",
      h4: "text-xl font-semibold tracking-tight",
      p: "leading-7",
      blockquote: "border-l-2 border-border pl-4 italic",
      code: "bg-default rounded px-1 py-0.5 font-mono text-sm",
      lead: "text-xl text-muted",
      large: "text-lg font-semibold",
      small: "text-sm font-medium leading-none",
      muted: "text-sm text-muted",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

type TextVariantProps = VariantProps<typeof textVariants>;

const TextClassContext = React.createContext<string | undefined>(undefined);

interface TextProps
  extends React.ComponentPropsWithoutRef<typeof RNText>,
    TextVariantProps {}

/**
 * Themed Text component with variants.
 * Defaults to `text-foreground` so you don't need to set it manually.
 *
 * @example
 * <Text>Default foreground text</Text>
 * <Text variant="h1">Heading 1</Text>
 * <Text variant="muted">Muted text</Text>
 */
function Text({ className, variant = "default", ...props }: TextProps) {
  const textClass = React.useContext(TextClassContext);
  return (
    <RNText
      className={cn(textVariants({ variant }), textClass, className)}
      {...props}
    />
  );
}

export { Text, TextClassContext, textVariants };
export type { TextProps, TextVariantProps };
