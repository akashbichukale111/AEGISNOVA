"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ShieldAlert,
  LayoutDashboard,
  GitBranch,
  FileSearch,
  Activity,
  Wrench,
  Bot,
  Scale,
  ScrollText,
  Settings,
  Sparkles,
  ChevronRight,
  Moon,
  Zap,
  GitPullRequest,
} from "lucide-react";
import { Badge } from "../ui/Badge";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: string;
  badgeVariant?: "demo" | "planned" | "critical" | "connected" | "success" | "warning";
}

const NAV_ITEMS: NavItem[] = [
  {
    label: "Overview",
    href: "/",
    icon: LayoutDashboard,
  },
  {
    label: "Proof-Carrying PRs",
    href: "/engineering",
    icon: GitPullRequest,
    badge: "PCPR",
    badgeVariant: "connected",
  },
  {
    label: "NightShift SDE",
    href: "/nightshift",
    icon: Moon,
    badge: "CONNECTED",
    badgeVariant: "connected",
  },
  {
    label: "Security Center",
    href: "/security",
    icon: ShieldAlert,
    badge: "3",
    badgeVariant: "critical",
  },
  {
    label: "Autonomous Operations",
    href: "/operations",
    icon: Bot,
    badge: "CONNECTED",
    badgeVariant: "connected",
  },
  {
    label: "Governance",
    href: "/governance",
    icon: Scale,
    badge: "UNWIND",
    badgeVariant: "connected",
  },
  {
    label: "Evidence Center",
    href: "/evidence",
    icon: FileSearch,
    badge: "CONNECTED",
    badgeVariant: "connected",
  },
  {
    label: "Impact Intelligence",
    href: "/causal-impact",
    icon: Activity,
    badge: "CONNECTED",
    badgeVariant: "connected",
  },
  {
    label: "Repair Assurance",
    href: "/repair-assurance",
    icon: Wrench,
    badge: "CONNECTED",
    badgeVariant: "connected",
  },
  {
    label: "Repository & Impact",
    href: "/impact",
    icon: GitBranch,
  },
  {
    label: "Audit & Observability",
    href: "/audit",
    icon: ScrollText,
  },
  {
    label: "Settings & Integrations",
    href: "/settings",
    icon: Settings,
  },
];

export function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-64 shrink-0 bg-[#070A12] border-r border-[#172235] flex flex-col h-screen sticky top-0 select-none z-30">
      {/* Brand Header */}
      <div className="p-5 border-b border-[#172235]">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-700 flex items-center justify-center shadow-lg shadow-cyan-900/30 ring-1 ring-cyan-300/30">
            <Sparkles className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-1.5">
              <span className="font-extrabold tracking-wider text-base text-white">AEGISNOVA</span>
              <span className="text-[10px] font-mono px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/80">
                v1.0
              </span>
            </div>
            <p className="text-[11px] text-slate-400 font-medium">A New Standard for Safe AI</p>
          </div>
        </div>
      </div>

      {/* Navigation List */}
      <nav className="flex-1 overflow-y-auto p-3 space-y-1">
        <div className="px-3 py-1.5 text-[10px] font-mono font-semibold uppercase tracking-wider text-slate-500">
          Core Command Surface
        </div>
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const isActive = pathname === item.href;

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`group flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition-all duration-150 ${
                isActive
                  ? "bg-cyan-950/60 text-cyan-200 border border-cyan-700/60 shadow-[0_0_12px_rgba(6,182,212,0.15)]"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-900/70"
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <Icon
                  className={`h-4 w-4 shrink-0 transition-colors ${
                    isActive ? "text-cyan-400" : "text-slate-500 group-hover:text-slate-300"
                  }`}
                />
                <span className="truncate">{item.label}</span>
              </div>

              <div className="flex items-center gap-1 shrink-0">
                {item.badge && (
                  <Badge variant={item.badgeVariant ?? "neutral"} size="sm">
                    {item.badge}
                  </Badge>
                )}
                {isActive && <ChevronRight className="h-3.5 w-3.5 text-cyan-400" />}
              </div>
            </Link>
          );
        })}
      </nav>

      {/* Governance & NVIDIA NIM Footer */}
      <div className="p-3 border-t border-[#172235] bg-[#0A0F1A]/80 space-y-2">
        <div className="p-2.5 rounded-xl bg-emerald-950/30 border border-emerald-800/40 text-xs">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-mono font-semibold text-emerald-400 flex items-center gap-1.5">
              <Zap className="h-3 w-3 text-emerald-400" />
              NVIDIA NIM ACCELERATED
            </span>
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
          </div>
          <div className="flex items-center justify-between font-mono text-[10px] text-slate-400 mt-1">
            <span>Hopper GH100</span>
            <span className="text-emerald-300 font-semibold">18.4ms FP8</span>
          </div>
        </div>

        <div className="p-2.5 rounded-xl bg-slate-900/90 border border-slate-800 text-xs space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-mono text-slate-400">UNWIND Governance</span>
            <span className="h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
          </div>
          <div className="flex items-center justify-between font-mono text-[11px]">
            <span className="text-slate-400">Warrant Ledger:</span>
            <span className="font-bold text-cyan-300">1,450 bp</span>
          </div>
        </div>
      </div>
    </aside>
  );
}
