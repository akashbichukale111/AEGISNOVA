import React from "react";

interface CardProps {
  children: React.ReactNode;
  className?: string;
  hover?: boolean;
  onClick?: () => void;
}

export function Card({ children, className = "", hover = false, onClick }: CardProps) {
  return (
    <div
      onClick={onClick}
      className={`rounded-xl bg-[#0D131F]/90 border border-[#1B2538] p-5 shadow-lg shadow-black/40 backdrop-blur-md transition-all ${
        hover ? "hover:border-cyan-600/40 hover:bg-[#11192A]/90 hover:shadow-cyan-950/20" : ""
      } ${className}`}
    >
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  badge,
  action,
  className = "",
}: {
  title: string;
  subtitle?: string;
  badge?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={`flex items-start justify-between gap-4 mb-4 ${className}`}>
      <div>
        <div className="flex items-center gap-2">
          <h3 className="font-semibold text-base text-slate-100 tracking-tight">{title}</h3>
          {badge}
        </div>
        {subtitle && <p className="text-xs text-slate-400 mt-1 leading-relaxed">{subtitle}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}
