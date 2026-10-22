import React from "react";

export type BadgeVariant =
  | "critical"
  | "high"
  | "medium"
  | "low"
  | "info"
  | "success"
  | "warning"
  | "neutral"
  | "demo"
  | "connected"
  | "not_connected"
  | "planned";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  size?: "sm" | "md";
  className?: string;
}

export function Badge({ children, variant = "neutral", size = "sm", className = "" }: BadgeProps) {
  const sizeClasses = size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-sm";

  const variantClasses: Record<BadgeVariant, string> = {
    critical: "bg-red-950/70 text-red-400 border border-red-800/60 shadow-[0_0_8px_rgba(239,68,68,0.2)]",
    high: "bg-orange-950/70 text-orange-400 border border-orange-800/60",
    medium: "bg-amber-950/70 text-amber-400 border border-amber-800/60",
    low: "bg-blue-950/70 text-blue-400 border border-blue-800/60",
    info: "bg-cyan-950/70 text-cyan-400 border border-cyan-800/60",
    success: "bg-emerald-950/70 text-emerald-400 border border-emerald-800/60 shadow-[0_0_8px_rgba(16,185,129,0.2)]",
    warning: "bg-yellow-950/70 text-yellow-400 border border-yellow-800/60",
    neutral: "bg-slate-900 text-slate-300 border border-slate-700/60",
    demo: "bg-purple-950/80 text-purple-300 border border-purple-700/60 font-mono tracking-wider font-semibold",
    connected: "bg-emerald-950/80 text-emerald-300 border border-emerald-600/70 font-mono text-[11px]",
    not_connected: "bg-rose-950/80 text-rose-300 border border-rose-600/70 font-mono text-[11px]",
    planned: "bg-slate-800 text-slate-400 border border-slate-700 font-mono text-[11px]",
  };

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-md font-medium tracking-wide transition-colors ${sizeClasses} ${variantClasses[variant]} ${className}`}
    >
      {variant === "connected" && <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />}
      {variant === "critical" && <span className="h-1.5 w-1.5 rounded-full bg-red-400 animate-pulse" />}
      {children}
    </span>
  );
}
