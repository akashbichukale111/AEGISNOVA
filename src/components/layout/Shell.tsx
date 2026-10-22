"use client";

import React, { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { Modal } from "../ui/Modal";
import {
  Search,
  ShieldAlert,
  Scale,
  GitBranch,
  ScrollText,
  Settings,
  Terminal,
  ArrowRight,
} from "lucide-react";

interface ShellProps {
  children: React.ReactNode;
}

export function Shell({ children }: ShellProps) {
  const router = useRouter();
  const [isSearchOpen, setIsSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Global Ctrl+K keyboard shortcut
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setIsSearchOpen(true);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const commands = [
    { label: "Go to Security Center", href: "/security", icon: ShieldAlert, group: "Navigation" },
    { label: "Go to UNWIND Governance Inbox", href: "/governance", icon: Scale, group: "Navigation" },
    { label: "Go to Repository & Impact", href: "/impact", icon: GitBranch, group: "Navigation" },
    { label: "View Audit Trail & Telemetry", href: "/audit", icon: ScrollText, group: "Navigation" },
    { label: "Platform Integration Matrix", href: "/settings", icon: Settings, group: "System" },
  ];

  const filteredCommands = commands.filter((c) =>
    c.label.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex min-h-screen bg-[#070A10] text-slate-100 font-sans selection:bg-cyan-500 selection:text-black">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-x-hidden">
        <TopBar onOpenSearch={() => setIsSearchOpen(true)} />
        <main className="flex-1 p-6 lg:p-8 max-w-7xl w-full mx-auto space-y-8 animate-fadeIn">
          {children}
        </main>
      </div>

      {/* Global Command Palette */}
      <Modal
        isOpen={isSearchOpen}
        onClose={() => setIsSearchOpen(false)}
        title="AEGISNOVA Command Launcher"
        subtitle="Search modules, run workflows, or jump to operational surfaces"
        maxWidth="lg"
      >
        <div className="space-y-4">
          <div className="relative">
            <Search className="absolute left-3 top-3 h-4 w-4 text-slate-400" />
            <input
              type="text"
              placeholder="Type a command or module name..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              autoFocus
              className="w-full pl-10 pr-4 py-2.5 rounded-lg bg-slate-900 border border-slate-700 text-sm text-white focus:outline-none focus:border-cyan-500 placeholder-slate-500 font-mono"
            />
          </div>

          <div className="space-y-1 max-h-60 overflow-y-auto">
            {filteredCommands.length === 0 ? (
              <div className="p-4 text-center text-xs text-slate-500 font-mono">
                No matching command or destination found.
              </div>
            ) : (
              filteredCommands.map((cmd) => {
                const Icon = cmd.icon;
                return (
                  <button
                    key={cmd.href}
                    onClick={() => {
                      setIsSearchOpen(false);
                      router.push(cmd.href);
                    }}
                    className="w-full flex items-center justify-between p-2.5 rounded-lg text-left text-xs font-medium text-slate-200 hover:bg-slate-800/80 hover:text-white transition-colors group"
                  >
                    <div className="flex items-center gap-2.5">
                      <Icon className="h-4 w-4 text-cyan-400" />
                      <span>{cmd.label}</span>
                    </div>
                    <ArrowRight className="h-3.5 w-3.5 text-slate-600 group-hover:text-cyan-400 transition-colors" />
                  </button>
                );
              })
            )}
          </div>
        </div>
      </Modal>
    </div>
  );
}
