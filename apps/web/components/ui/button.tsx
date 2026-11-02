// Adapted from shadcn/ui (MIT) — see THIRD_PARTY_NOTICES.md.
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

// Pixel style: a notched frame with a bevel; pressing moves the button one pixel down and turns the
// bevel inwards. Ghost buttons have no frame. Icons keep their own whole-pixel size (components/icons).
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 text-sm whitespace-nowrap outline-none select-none focus-visible:outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground pixel-frame pixel-raised hover:bg-primary/90 focus-visible:[--frame-color:var(--color-ring)] active:translate-y-(--px) active:pixel-sunken",
        destructive:
          "bg-destructive text-destructive-foreground pixel-frame pixel-raised [--frame-color:var(--color-destructive)] hover:bg-destructive/90 focus-visible:[--frame-color:var(--color-ring)] active:translate-y-(--px) active:pixel-sunken",
        outline:
          "bg-card text-card-foreground pixel-frame pixel-raised hover:bg-accent hover:text-accent-foreground focus-visible:[--frame-color:var(--color-ring)] active:translate-y-(--px) active:pixel-sunken",
        ghost: "hover:bg-accent hover:text-accent-foreground focus-visible:bg-accent",
      },
      size: {
        default: "h-10 px-4",
        sm: "h-9 px-3",
        icon: "size-10",
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
