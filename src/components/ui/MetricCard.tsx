import React from "react";
import { Card } from "./Card";
import { Badge } from "./Badge";

interface MetricCardProps {
  label: string;
  value: string | number;
  subtext?: string;
  icon?: React.ReactNode;
  trend?: {
    direction: "up" | "down" | "neutral";
    value: string;
  };
  severity?: "normal" | "warning" | "critical" | "success";
  isDemo?: boolean;
  onClick?: () => void;
}

export function MetricCard({
  label,
  value,
  subtext,
  icon,
  trend,
  severity = "normal",
  isDemo = false,
  onClick,
}: MetricCardProps) {
  const severityBorder = {
    normal: "border-[#1B2538] hover:border-slate-600/50",
    warning: "border-amber-900/50 hover:border-amber-600/60 bg-amber-950/10",
    critical: "border-red-900/60 hover:border-red-600/70 bg-red-950/10",
    success: "border-emerald-900/50 hover:border-emerald-600/60 bg-emerald-950/10",
  }[severity];

  return (
    <Card
      className={`relative overflow-hidden cursor-pointer transition-all duration-200 select-none ${severityBorder} ${
        onClick ? "hover:-translate-y-0.5" : ""
      }`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between">
        <div className="space-y-1">
          <div className="flex items-center gap-1.5">
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">
              {label}
            </span>
            {isDemo && (
              <Badge variant="demo" size="sm">
                DEMO
              </Badge>
            )}
          </div>
          <div className="text-2xl sm:text-3xl font-bold tracking-tight text-white font-mono">
            {value}
          </div>
        </div>
        {icon && (
          <div className="p-2.5 rounded-lg bg-slate-800/60 text-cyan-400 border border-slate-700/50 shrink-0">
            {icon}
          </div>
        )}
      </div>

      {(subtext || trend) && (
        <div className="mt-3 flex items-center justify-between text-xs border-t border-slate-800/60 pt-2 text-slate-400">
          <span>{subtext}</span>
          {trend && (
            <span
              className={`font-mono font-medium ${
                trend.direction === "up"
                  ? severity === "critical"
                    ? "text-red-400"
                    : "text-emerald-400"
                  : trend.direction === "down"
                  ? severity === "critical"
                    ? "text-emerald-400"
                    : "text-red-400"
                  : "text-slate-400"
              }`}
            >
              {trend.value}
            </span>
          )}
        </div>
      )}
    </Card>
  );
}
