// Adapted from shadcn/ui (MIT) — see THIRD_PARTY_NOTICES.md.
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

// Clean style: a hairline frame (pixel-frame), soft corners, a quiet hover; pressing dims it.
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-lg text-sm font-medium whitespace-nowrap transition-colors outline-none select-none focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground hover:bg-primary/90 focus-visible:ring-2 focus-visible:ring-ring/50 active:bg-primary/80",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90 focus-visible:ring-2 focus-visible:ring-ring/50 active:bg-destructive/80",
        outline:
          "bg-card text-card-foreground pixel-frame rounded-lg hover:bg-accent hover:text-accent-foreground focus-visible:[--frame-color:var(--color-ring)] active:bg-accent/70",
        ghost: "hover:bg-accent hover:text-accent-foreground focus-visible:bg-accent",
      },
      size: {
        default: "h-9 px-3.5",
        sm: "h-8 px-3",
        icon: "size-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
);

type ButtonProps = ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean };

export function Button({ className, variant, size, asChild = false, ...props }: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  return <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}
