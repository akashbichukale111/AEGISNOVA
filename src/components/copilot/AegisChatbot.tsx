"use client";

import React, { useState, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Bot,
  Sparkles,
  Send,
  X,
  Minimize2,
  Maximize2,
  ShieldAlert,
  ShieldCheck,
  CheckCircle2,
  Clock,
  Moon,
  Zap,
  FolderGit2,
  ExternalLink,
  RotateCcw,
  AlertTriangle,
  Play,
  FileCode,
  Globe,
  ArrowRight,
  HelpCircle,
  Database,
  Cpu
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { CopilotChatMessage, IncidentSeverity, AutonomyResolutionAction } from "@/contracts";

interface AegisChatbotProps {
  embedded?: boolean;
  defaultRepo?: string;
}

export function AegisChatbot({ embedded = false, defaultRepo = "demo/payments-service" }: AegisChatbotProps) {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(embedded);
  const [isMinimized, setIsMinimized] = useState(false);
  const [repoUrl, setRepoUrl] = useState(defaultRepo);
  const [inputMessage, setInputMessage] = useState("");
  const [isProcessing, setIsProcessing] = useState(false);
  const [actionNotice, setActionNotice] = useState<string | null>(null);

  const [messages, setMessages] = useState<CopilotChatMessage[]>([
    {
      id: "welcome-msg",
      role: "assistant",
      content:
        `👋 **Namaste! I am your AEGISNOVA Autonomous Engineering Copilot.**\n\n` +
        `Paste any **GitHub repository link** and describe what needs to be done. Our multi-agent team will triage and resolve it:\n\n` +
        `• 🟢 **LOW / MEDIUM Severity:** Fully autonomous self-healing! Zero human intervention—**no SDE wakeup at 3:00 AM**. If the same issue happens tomorrow, it will be automatically resolved from knowledge memory.\n` +
        `• 🔴 **HIGH / CRITICAL Severity:** The agents synthesize the patch, run tests, and research Tavily CVE citations, but hold execution for **ONE-CLICK SDE HUMAN APPROVAL**.\n\n` +
        `Try selecting a quick prompt below or paste your repository link!`,
      timestamp: new Date().toISOString(),
      suggestedPrompts: [
        "Fix SQL injection vulnerability in payments service",
        "Audit requirements.txt and pin unpinned dependencies",
        "Run 3:00 AM NightShift autonomous security patrol",
        "Test recurring memory self-healing"
      ]
    }
  ]);

  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (isOpen && !isMinimized) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, isOpen, isMinimized]);

  // Handle Send Message
  const handleSendMessage = async (textToSend: string = inputMessage) => {
    const text = textToSend.trim();
    if (!text || isProcessing) return;

    const userMsg: CopilotChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: text,
      timestamp: new Date().toISOString(),
      repoTarget: repoUrl
    };

    setMessages((prev) => [...prev, userMsg]);
    setInputMessage("");
    setIsProcessing(true);

    try {
      const res = await fetch("/api/copilot/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          repoUrl
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.reply) {
          setMessages((prev) => [...prev, data.reply]);
        }
      } else {
        const errData = await res.json();
        throw new Error(errData.error || "Failed to process message.");
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: `⚠️ Communication error: ${(err as Error).message}. Local resilience fallback engaged.`,
          timestamp: new Date().toISOString()
        }
      ]);
    } finally {
      setIsProcessing(false);
    }
  };

  // Handle 1-Click SDE Approval for High-Severity Incidents
  const handleApproveIncident = async (incidentId?: string) => {
    if (!incidentId) return;
    setIsProcessing(true);
    setActionNotice("Authorizing UNWIND warrant (-150 bp)...");

    try {
      const res = await fetch("/api/copilot/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ incidentId })
      });

      if (res.ok) {
        const data = await res.json();
        setActionNotice("SDE Approval confirmed! PCPR execution started.");
        setMessages((prev) => [
          ...prev,
          {
            id: `approved-${Date.now()}`,
            role: "assistant",
            content:
              `✅ **[UNWIND Countersigned] 1-CLICK SDE APPROVAL GRANTED!**\n\n` +
              `• **Incident ID:** \`${incidentId}\`\n` +
              `• **UNWIND Warrant Debited:** \`-150 bp\`\n` +
              `• **Run ID:** \`${data.runId}\`\n` +
              `• **Delivery Pipeline:** 12-stage PCPR delivery is actively executing in background.\n\n` +
              `👉 You can monitor the real deterministic test stream and manifest on the **[Proof-Carrying PRs](/engineering)** page.`,
            timestamp: new Date().toISOString(),
            runId: data.runId,
            suggestedPrompts: ["Go to /engineering to view live logs"]
          }
        ]);
      }
    } catch (err) {
      console.error("Approval error:", err);
    } finally {
      setIsProcessing(false);
      setTimeout(() => setActionNotice(null), 4000);
    }
  };

  if (!embedded && !isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2.5 px-4 py-3 rounded-full bg-gradient-to-r from-cyan-600 via-indigo-600 to-cyan-500 text-white font-mono text-xs font-semibold shadow-[0_0_24px_rgba(6,182,212,0.45)] hover:shadow-[0_0_32px_rgba(6,182,212,0.65)] hover:scale-105 transition-all group border border-cyan-400/40"
      >
        <div className="relative">
          <Bot className="h-5 w-5 text-white animate-bounce" />
          <span className="absolute -top-1 -right-1 h-2.5 w-2.5 rounded-full bg-emerald-400 ring-2 ring-slate-950 animate-pulse" />
        </div>
        <span className="font-bold tracking-wide">AEGIS Copilot</span>
        <span className="text-[10px] bg-slate-950/60 px-2 py-0.5 rounded-full border border-cyan-400/30 text-cyan-200">
          3 AM SDE PATROL
        </span>
      </button>
    );
  }

  return (
    <div
      className={
        embedded
          ? "w-full rounded-2xl bg-[#0B0F19] border border-[#172235] shadow-2xl flex flex-col h-[650px] overflow-hidden"
          : `fixed bottom-6 right-6 z-50 w-[95vw] sm:w-[480px] rounded-2xl bg-[#0B0F19] border border-cyan-800/60 shadow-[0_12px_48px_rgba(0,0,0,0.8)] flex flex-col transition-all overflow-hidden ${
              isMinimized ? "h-14" : "h-[650px] max-h-[85vh]"
            }`
      }
    >
      {/* Header Bar */}
      <div className="p-3.5 bg-gradient-to-r from-[#0F172A] via-[#111C33] to-[#0A1020] border-b border-[#1E293B] flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-cyan-500 to-indigo-600 flex items-center justify-center shadow-md shadow-cyan-950/60 ring-1 ring-cyan-400/30">
            <Bot className="h-4 w-4 text-white" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-xs font-mono font-bold text-white tracking-wide">
                AEGISNOVA Autonomous Copilot
              </h3>
              <Badge variant="connected">ACTIVE</Badge>
            </div>
            <p className="text-[10px] text-slate-400 font-mono">
              NightShift SDE • Low/Med Auto-Heal • High SDE Approval Gate
            </p>
          </div>
        </div>

        {!embedded && (
          <div className="flex items-center gap-1.5 text-slate-400">
            <button
              onClick={() => setIsMinimized(!isMinimized)}
              className="p-1 rounded hover:bg-slate-800 hover:text-white"
            >
              {isMinimized ? <Maximize2 className="h-3.5 w-3.5" /> : <Minimize2 className="h-3.5 w-3.5" />}
            </button>
            <button
              onClick={() => setIsOpen(false)}
              className="p-1 rounded hover:bg-slate-800 hover:text-white"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}
      </div>

      {!isMinimized && (
        <>
          {/* GitHub Repository Target Bar */}
          <div className="p-2.5 bg-[#070A10] border-b border-[#172235] flex items-center justify-between gap-2 text-xs font-mono">
            <div className="flex items-center gap-2 flex-1 min-w-0">
              <FolderGit2 className="h-4 w-4 text-cyan-400 shrink-0" />
              <input
                type="text"
                placeholder="Paste GitHub URL or repo name (e.g. https://github.com/...)"
                value={repoUrl}
                onChange={(e) => setRepoUrl(e.target.value)}
                className="bg-transparent text-slate-200 placeholder-slate-500 focus:outline-none w-full text-[11px]"
              />
            </div>
            <span className="text-[10px] px-2 py-0.5 rounded bg-cyan-950/80 text-cyan-300 border border-cyan-800 shrink-0">
              TARGET
            </span>
          </div>

          {actionNotice && (
            <div className="p-2 bg-cyan-950/80 border-b border-cyan-700 text-xs text-cyan-200 font-mono text-center animate-fadeIn">
              {actionNotice}
            </div>
          )}

          {/* Messages Stream */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4 bg-[#070A10]/60">
            {messages.map((msg) => {
              const isUser = msg.role === "user";
              return (
                <div
                  key={msg.id}
                  className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}
                >
                  <div className="flex items-center gap-1.5 mb-1 px-1 text-[10px] font-mono text-slate-500">
                    <span>{isUser ? "You (SDE Operator)" : "AEGISNOVA Multi-Agent Core"}</span>
                    <span>•</span>
                    <span>{new Date(msg.timestamp).toLocaleTimeString()}</span>
                  </div>

                  <div
                    className={`p-3.5 rounded-xl max-w-[92%] text-xs font-sans leading-relaxed border transition-all ${
                      isUser
                        ? "bg-gradient-to-r from-cyan-950/80 to-blue-950/80 border-cyan-700/60 text-slate-100 rounded-tr-none"
                        : "bg-[#0B0F19] border-[#172235] text-slate-200 rounded-tl-none shadow-md"
                    }`}
                  >
                    {/* Severity & Policy Tag if assistant */}
                    {!isUser && msg.severity && (
                      <div className="flex items-center gap-2 mb-2 pb-2 border-b border-slate-800">
                        <Badge
                          variant={
                            msg.severity === "CRITICAL"
                              ? "critical"
                              : msg.severity === "HIGH"
                              ? "warning"
                              : "success"
                          }
                        >
                          {msg.severity} RISK
                        </Badge>
                        <span className="text-[10px] font-mono text-slate-400">
                          {msg.autonomyAction === "AUTO_RESOLVED_NO_SDE_WAKEUP" && "🟢 Auto-Resolved (No SDE Wakeup)"}
                          {msg.autonomyAction === "RECURRENT_HEALED_FROM_MEMORY" && "🧠 Recurrent Pattern Auto-Healed"}
                          {msg.autonomyAction === "WAITING_FOR_SDE_APPROVAL" && "⏳ 1-Click SDE Approval Required"}
                          {msg.autonomyAction === "SDE_APPROVED_AND_EXECUTED" && "🚀 Approved & Delivering"}
                        </span>
                      </div>
                    )}

                    <div className="whitespace-pre-wrap">{msg.content}</div>

                    {/* Interactive 1-Click Approval Box for HIGH / CRITICAL */}
                    {!isUser && msg.executionPreview?.requiresApproval && msg.incidentId && (
                      <div className="mt-3 p-3 rounded-lg bg-rose-950/30 border border-rose-800/60 space-y-2">
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-1.5 text-rose-300 font-mono font-semibold text-[11px]">
                            <AlertTriangle className="h-3.5 w-3.5 text-rose-400" />
                            <span>1-Click SDE Human Approval Gate</span>
                          </div>
                          <span className="text-[10px] font-mono text-cyan-300">
                            Warrant Debit: -{msg.executionPreview.warrantDebitBp} bp
                          </span>
                        </div>
                        <p className="text-[11px] text-slate-300">
                          All patch code synthesized & tests pre-checked. Click below to grant authorization and deliver pull request:
                        </p>
                        <Button
                          variant="primary"
                          size="sm"
                          onClick={() => handleApproveIncident(msg.incidentId)}
                          disabled={isProcessing}
                          className="w-full text-xs font-mono bg-gradient-to-r from-emerald-600 to-cyan-600 hover:from-emerald-500 hover:to-cyan-500 text-white font-bold py-1.5 flex items-center justify-center gap-2 shadow-lg shadow-emerald-950/60"
                        >
                          <Play className="h-3.5 w-3.5" />
                          Approve & Execute Patch Now
                        </Button>
                      </div>
                    )}

                    {/* Diff Preview if present */}
                    {msg.executionPreview?.diffSnippet && (
                      <div className="mt-2.5">
                        <div className="text-[10px] font-mono text-slate-400 mb-1 flex items-center gap-1">
                          <FileCode className="h-3 w-3 text-cyan-400" />
                          <span>Remediation Diff Preview</span>
                        </div>
                        <pre className="p-2 bg-[#070A10] rounded border border-slate-800 text-[10px] font-mono text-slate-300 overflow-x-auto">
                          {msg.executionPreview.diffSnippet}
                        </pre>
                      </div>
                    )}

                    {/* Run Link if triggered */}
                    {msg.runId && (
                      <div className="mt-2 pt-2 border-t border-slate-800 flex items-center justify-between text-[11px] font-mono">
                        <span className="text-slate-400">Run ID: {msg.runId}</span>
                        <button
                          onClick={() => router.push("/engineering")}
                          className="text-cyan-400 hover:text-cyan-300 flex items-center gap-1"
                        >
                          <span>Open in /engineering</span>
                          <ArrowRight className="h-3 w-3" />
                        </button>
                      </div>
                    )}
                  </div>

                  {/* Suggested Quick Prompt Chips */}
                  {msg.suggestedPrompts && (
                    <div className="flex flex-wrap gap-1.5 mt-2 max-w-[92%]">
                      {msg.suggestedPrompts.map((p, idx) => (
                        <button
                          key={idx}
                          onClick={() => {
                            if (p === "Go to /engineering to view live logs") {
                              router.push("/engineering");
                            } else {
                              handleSendMessage(p);
                            }
                          }}
                          className="text-[10px] font-mono px-2 py-1 rounded-md bg-[#0F172A] hover:bg-cyan-950/60 text-slate-300 hover:text-cyan-200 border border-slate-800 transition-all text-left"
                        >
                          ⚡ {p}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
            <div ref={messagesEndRef} />
          </div>

          {/* Input Box */}
          <div className="p-3 bg-[#0B0F19] border-t border-[#172235] space-y-2 shrink-0">
            <div className="flex items-center gap-2">
              <input
                type="text"
                placeholder="Ask AEGIS Copilot (e.g. 'Fix CVE vulnerability in auth.py', 'Audit repo')..."
                value={inputMessage}
                onChange={(e) => setInputMessage(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSendMessage()}
                disabled={isProcessing}
                className="flex-1 bg-[#070A10] border border-[#172235] rounded-xl px-3.5 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
              />
              <Button
                variant="primary"
                size="sm"
                onClick={() => handleSendMessage()}
                disabled={isProcessing || !inputMessage.trim()}
                className="bg-cyan-600 hover:bg-cyan-500 text-white px-3 py-2 rounded-xl text-xs font-mono shrink-0 flex items-center gap-1.5"
              >
                <Send className="h-3.5 w-3.5" />
                <span>Send</span>
              </Button>
            </div>

            {/* Micro Telemetry Bar */}
            <div className="flex items-center justify-between text-[10px] font-mono text-slate-500 px-1">
              <span className="flex items-center gap-1">
                <Cpu className="h-2.5 w-2.5 text-cyan-400" />
                NVIDIA Hopper GH100 • Nebius
              </span>
              <span className="flex items-center gap-1">
                <Globe className="h-2.5 w-2.5 text-indigo-400" />
                Tavily 300k Quota Active
              </span>
              <span className="flex items-center gap-1">
                <Moon className="h-2.5 w-2.5 text-amber-400" />
                3 AM Patrol Ready
              </span>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
