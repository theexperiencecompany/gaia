import { cva } from "class-variance-authority";

export const raisedButtonVariants = cva(
  "inline-flex items-center justify-center overflow-hidden dark:bg-zinc-500 dark:text-white whitespace-nowrap  text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 relative bg-primary text-primary-foreground hover:bg-primary/90 border border-primary/50 shadow-md before:absolute before:inset-0 before:border-t before:border-white/40 before:bg-gradient-to-b before:from-white/20 before:to-transparent cursor-pointer transition-transform duration-200 active:scale-[0.96] subpixel-antialiased gap-2",
  {
    variants: {
      variant: {
        default: "",
        // Keep existing variants and add more if needed
      },
      size: {
        default: "h-10 px-4 py-2 rounded-xl before:rounded-xl",
        sm: "h-9 rounded-lg px-3 before:rounded-lg",
        lg: "h-11 rounded-lg px-8 before:rounded-lg",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);
