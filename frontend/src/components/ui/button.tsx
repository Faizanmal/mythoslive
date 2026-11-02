import { cva, type VariantProps } from "class-variance-authority";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva("inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50", {
  variants: {
    variant: {
      default: "bg-amber-300 px-4 py-2 text-slate-950 hover:bg-amber-200",
      outline: "border border-slate-600 px-4 py-2 hover:bg-slate-800",
      ghost: "px-3 py-2 hover:bg-slate-800",
    },
    size: { default: "h-10", sm: "h-8 text-sm", lg: "h-12 px-6 text-lg" },
  },
  defaultVariants: { variant: "default", size: "default" },
});

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, VariantProps<typeof buttonVariants> {}

export function Button({ className, variant, size, ...props }: ButtonProps) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
