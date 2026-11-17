import { Slot } from "@radix-ui/react-slot";
import type * as React from "react";
import type { VariantProps } from "tailwind-variants";

import { buttonVariants } from "@/components/ui/button-variants";
import { cn } from "@/lib/utils";

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp: React.ElementType = asChild ? Slot : "button";

  return (
    <Comp
      data-slot="button"
      className={cn(
        buttonVariants({ variant, size, className }),
        "cursor-pointer",
      )}
      {...props}
    />
  );
}

export { Button };
