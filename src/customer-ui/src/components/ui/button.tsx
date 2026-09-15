import { cn } from "@/lib/utils";
import type { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "ghost";

export function Button({
  className,
  variant = "primary",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-card px-4 py-2 text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-40",
        variant === "primary" && "bg-ink text-paper hover:bg-ink-raised",
        variant === "ghost" && "text-graphite hover:bg-paper-hair",
        className,
      )}
      {...props}
    />
  );
}
