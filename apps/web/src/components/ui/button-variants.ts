import { cva } from "class-variance-authority";

export const buttonVariants = cva(
  "inline-flex items-center active:scale-95 transition-all! duration-300 justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-all disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg:not([class*='size-'])]:size-4 shrink-0 [&_svg]:shrink-0 outline-none focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-xs hover:bg-primary/90",
        destructive:
          "bg-destructive text-white shadow-xs hover:bg-destructive/90 focus-visible:ring-destructive/20 dark:focus-visible:ring-destructive/40 dark:bg-destructive/60",
        outline:
          "border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:bg-input/30 dark:border-input dark:hover:bg-input/50",
        // Dark translucent pill over landing hero imagery. No `secondary`: in this
        // app `bg-secondary` resolves to HeroUI's purple, not a neutral.
        glass: "rounded-xl bg-black/60 text-white hover:bg-black/40",
        ghost:
          "hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
        ghostPrimary:
          "rounded-xl hover:bg-primary/20 hover:text-primary dark:hover:bg-accent/50",
        // Chat composer's round action buttons; composerActive is the toggled-open state.
        composer:
          "rounded-full border-none bg-zinc-700 fill-zinc-400 text-zinc-400 shadow-xs hover:bg-zinc-600/90",
        composerActive:
          "rounded-full border-none bg-primary/20 fill-zinc-400 text-primary shadow-xs hover:bg-primary/40",
        // Tinted primary pill (mail compose's AI options trigger).
        primarySoft:
          "border-none bg-primary/25 font-normal text-primary outline-hidden ring-0 hover:bg-primary/12",
        // Translucent round control over imagery (weather card settings).
        frosted: "rounded-full bg-white/10 text-white hover:bg-white/20",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        sm: "h-8 rounded-md gap-1.5 px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);
