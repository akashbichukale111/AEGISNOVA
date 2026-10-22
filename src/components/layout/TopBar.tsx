"use client";

import React, { useState } from "react";
import {
  Search,
  Bell,
  CheckCircle2,
  AlertTriangle,
  FolderGit2,
  Terminal,
  ShieldCheck,
  ChevronDown,
} from "lucide-react";
import { Badge } from "../ui/Badge";
import { INITIAL_REPOSITORIES } from "../../lib/demo-data";

interface TopBarProps {
  onOpenSearch?: () => void;
  isDemoMode?: boolean;
}

export function TopBar({ onOpenSearch, isDemoMode = true }: TopBarProps) {
  const [selectedRepo, setSelectedRepo] = useState(INITIAL_REPOSITORIES[0].name);
  const [isNotificationsOpen, setIsNotificationsOpen] = useState(false);

  return (
    <header className="h-14 border-b border-[#172235] bg-[#070A12]/90 backdrop-blur-md px-6 flex items-center justify-between sticky top-0 z-20 select-none">
      {/* Left: Repository Context Selector */}
      <div className="flex items-center gap-4">
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900/90 border border-slate-800 text-xs text-slate-200">
          <FolderGit2 className="h-3.5 w-3.5 text-cyan-400" />
          <span className="font-mono font-medium text-slate-300">Target Workspace:</span>
          <select
            value={selectedRepo}
            onChange={(e) => setSelectedRepo(e.target.value)}
            aria-label="Target Workspace Repository"
            className="bg-transparent font-semibold text-white focus:outline-none cursor-pointer"
          >
            {INITIAL_REPOSITORIES.map((repo) => (
              <option key={repo.id} value={repo.name} className="bg-[#0B0F19] text-slate-200">
                {repo.name}
              </option>
            ))}
          </select>
        </div>

        {/* Global Environment Badge (Non-negotiable requirement for truth in UI) */}
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-purple-950/80 border border-purple-700/80 text-[11px] font-mono font-semibold text-purple-200">
            <span className="h-1.5 w-1.5 rounded-full bg-purple-400 animate-pulse" />
            ENV: LOCAL (DEMO PIPELINE)
          </span>
          <span className="hidden md:inline-flex items-center gap-1 text-[11px] font-mono text-slate-400">
            <ShieldCheck className="h-3.5 w-3.5 text-emerald-400" />
            Zero-Cloud / No External Secrets
          </span>
        </div>
      </div>

      {/* Right: Search / Actions / Status */}
      <div className="flex items-center gap-3">
        {/* Quick Search Launcher */}
        <button
          onClick={onOpenSearch}
          className="hidden sm:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-400 hover:text-slate-200 hover:border-slate-700 transition-colors"
        >
          <Search className="h-3.5 w-3.5" />
          <span>Quick command...</span>
          <kbd className="px-1.5 py-0.5 rounded bg-slate-800 border border-slate-700 text-[10px] font-mono text-slate-400">
            Ctrl+K
          </kbd>
        </button>

        {/* Notifications Icon with popover toggle */}
        <div className="relative">
          <button
            onClick={() => setIsNotificationsOpen(!isNotificationsOpen)}
            className="p-2 rounded-lg bg-slate-900 border border-slate-800 text-slate-400 hover:text-white hover:bg-slate-800 transition-colors relative"
            title="Operational Notifications"
          >
            <Bell className="h-4 w-4" />
            <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-cyan-400" />
          </button>

          {isNotificationsOpen && (
            <div className="absolute right-0 mt-2 w-80 rounded-xl bg-[#0D131F] border border-[#22314E] shadow-2xl p-4 text-xs text-slate-300 z-50 space-y-3">
              <div className="flex items-center justify-between border-b border-slate-800 pb-2">
                <span className="font-semibold text-white">Notifications</span>
                <Badge variant="demo" size="sm">
                  DEMO FEED
                </Badge>
              </div>
              <div className="space-y-2">
                <div className="p-2.5 rounded-lg bg-red-950/40 border border-red-900/40 text-red-300">
                  <div className="font-semibold flex items-center gap-1">
                    <AlertTriangle className="h-3.5 w-3.5" /> High Risk Write Paused
                  </div>
                  <div className="text-[11px] text-slate-400 mt-1">
                    Patch FIND-SEC-101 is awaiting human UNWIND countersignature.
                  </div>
                </div>
                <div className="p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-slate-300">
                  <div className="font-semibold flex items-center gap-1">
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" /> Warrant Ledger Folded
                  </div>
                  <div className="text-[11px] text-slate-400 mt-1">
                    Deterministic zero-model fold rederived bit-equal balance (1,450 bp).
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* User / Persona Badge */}
        <div className="flex items-center gap-2 pl-2 border-l border-slate-800">
          <div className="h-7 w-7 rounded-full bg-cyan-900/60 border border-cyan-500/40 flex items-center justify-center text-cyan-300 font-mono text-xs font-bold">
            AN
          </div>
          <span className="hidden lg:inline text-xs font-medium text-slate-300">Security Lead</span>
        </div>
      </div>
    </header>
  );
}
