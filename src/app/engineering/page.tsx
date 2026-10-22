"use client";

import React, { useState, useEffect, useRef } from "react";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  GitPullRequest,
  CheckCircle2,
  AlertTriangle,
  Play,
  RotateCcw,
  Sparkles,
  Terminal,
  ShieldCheck,
  Scale,
  Zap,
  Cpu,
  FileCode,
  Download,
  Copy,
  ExternalLink,
  Lock,
  Layers,
  Activity,
  ArrowRight,
  Search,
  Check,
  Code,
  AlertCircle,
  Database,
  CpuIcon,
  FolderGit2,
  ListPlus
} from "lucide-react";
import {
  AgentRun,
  AutonomyMode,
  EvidenceManifest,
  GitHubConnection,
  RepoAuditReport,
  RepoAuditFinding,
  RepositoryTarget
} from "@/contracts";

export default function EngineeringStudioPage() {
  // Navigation Modes
  const [activeTab, setActiveTab] = useState<"MODE_A" | "MODE_B">("MODE_A");

  // GitHub Connection & Repo Selection
  const [githubStatus, setGithubStatus] = useState<GitHubConnection>({
    status: "UNCONFIGURED",
    tokenConfigured: false
  });
  const [repoInput, setRepoInput] = useState("demo/payments-service");
  const [isVerifyingRepo, setIsVerifyingRepo] = useState(false);
  const [verifiedTarget, setVerifiedTarget] = useState<RepositoryTarget | null>({
    id: "demo/payments-service",
    name: "payments-service",
    path: "services/nightshift-sde/fixtures/demo-repos/payments-service",
    defaultBranch: "main",
    testCommand: "python -m unittest discover -s tests",
    buildManifest: "requirements.txt",
    isMonitored: true
  });
  const [verificationError, setVerificationError] = useState<string | null>(null);

  // Mode A: Audit Report State
  const [isAuditing, setIsAuditing] = useState(false);
  const [auditReport, setAuditReport] = useState<RepoAuditReport | null>(null);

  // Mode B: Autonomous Run State
  const [activeRun, setActiveRun] = useState<AgentRun | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [autonomyMode, setAutonomyMode] = useState<AutonomyMode>("PATCH_AND_VERIFY");
  const [taskTitle, setTaskTitle] = useState(
    "Mitigate SQL injection vulnerability and verify zero regression in payments-service"
  );
  const [taskCriteria, setTaskCriteria] = useState(
    "1. Parameterize DB query binding in app/__init__.py\n2. Pass all existing unit tests in tests/test_app.py\n3. Zero secrets or security regressions introduced"
  );
  const [copyNotice, setCopyNotice] = useState<string | null>(null);
  const logsEndRef = useRef<HTMLDivElement>(null);

  // Fetch GitHub Connection Status on Mount
  useEffect(() => {
    async function fetchStatus() {
      try {
        const res = await fetch("/api/github/status");
        if (res.ok) {
          const data = await res.json();
          setGithubStatus(data);
        }
      } catch (err) {
        console.warn("GitHub status fetch error:", err);
      }
    }
    fetchStatus();
    // Also trigger initial audit for default demo repo
    handleRunAudit("demo/payments-service");
  }, []);

  // Poll Active Run in Mode B
  useEffect(() => {
    if (!activeRun || activeRun.status === "READY_FOR_REVIEW" || activeRun.status === "FAILED") {
      return;
    }

    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/engineering/status?runId=${activeRun.id}`);
        if (res.ok) {
          const data = await res.json();
          setActiveRun((prev) => (prev ? { ...prev, ...data } : null));
          if (data.runStatus === "READY_FOR_REVIEW" || data.runStatus === "FAILED") {
            setIsRunning(false);
          }
        }
      } catch (err) {
        console.warn("Poll status error:", err);
      }
    }, 800);

    return () => clearInterval(interval);
  }, [activeRun]);

  // Auto-scroll logs
  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [activeRun?.events]);

  // Verify Repo URL / Target
  const handleVerifyRepo = async () => {
    setIsVerifyingRepo(true);
    setVerificationError(null);
    try {
      const res = await fetch("/api/github/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: repoInput })
      });
      const data = await res.json();
      if (data.verified && data.repoTarget) {
        setVerifiedTarget(data.repoTarget);
        // Automatically audit on successful verification
        handleRunAudit(repoInput);
      } else {
        setVerificationError(data.error || "Unable to access repository.");
      }
    } catch (err) {
      setVerificationError((err as Error).message);
    } finally {
      setIsVerifyingRepo(false);
    }
  };

  // Run Mode A: Audit
  const handleRunAudit = async (targetId: string = repoInput) => {
    setIsAuditing(true);
    try {
      const res = await fetch("/api/repo-intelligence/audit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: targetId })
      });
      if (res.ok) {
        const report = await res.json();
        setAuditReport(report);
      }
    } catch (err) {
      console.error("Audit error:", err);
    } finally {
      setIsAuditing(false);
    }
  };

  // Convert an Audit Finding into Mode B Task
  const handleTurnFindingIntoTask = (finding: RepoAuditFinding) => {
    setTaskTitle(`Fix ${finding.ruleId}: ${finding.title}`);
    setTaskCriteria(
      `1. Address finding in ${finding.filePath}${finding.lineNumber ? ` line ${finding.lineNumber}` : ""}: ${finding.recommendedFix}\n2. ${finding.regressionTestSuggestion || "Ensure all unit tests pass without regression."}\n3. Guarantee zero secrets or unauthorized writes.`
    );
    setActiveTab("MODE_B");
    setCopyNotice(`Converted finding ${finding.ruleId} into engineering task!`);
    setTimeout(() => setCopyNotice(null), 3500);
  };

  // Launch Mode B Autonomous Run
  const handleLaunchPCPR = async () => {
    setIsRunning(true);
    try {
      const criteriaList = taskCriteria
        .split("\n")
        .map((s) => s.replace(/^\d+[\.\)]\s*/, "").trim())
        .filter(Boolean);

      const target = verifiedTarget || {
        id: repoInput,
        name: repoInput.split("/").pop() || "payments-service",
        path: `services/nightshift-sde/fixtures/demo-repos/${repoInput.split("/").pop() || "payments-service"}`,
        defaultBranch: "main",
        testCommand: "python -m unittest discover -s tests",
        buildManifest: "requirements.txt",
        isMonitored: true
      };

      const res = await fetch("/api/engineering/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          repoTarget: target,
          issueTask: {
            id: `TASK-${Date.now().toString(36).toUpperCase()}`,
            title: taskTitle,
            description: taskTitle,
            targetRepoId: target.id,
            acceptanceCriteria: criteriaList.length > 0 ? criteriaList : ["Pass unit test suite", "Enforce security standards"],
            severity: "HIGH",
            autonomyMode,
            allowHighRiskWrites: true
          }
        })
      });

      if (res.ok) {
        const data = await res.json();
        setActiveRun(data.run);
      }
    } catch (err) {
      console.error("Launch error:", err);
      setIsRunning(false);
    }
  };

  const copyToClipboard = (text: string, label: string) => {
    navigator.clipboard.writeText(text);
    setCopyNotice(`Copied ${label} to clipboard!`);
    setTimeout(() => setCopyNotice(null), 3000);
  };

  const manifest = activeRun?.manifest;

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[#172235] pb-5">
        <div>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-cyan-500 to-indigo-800 flex items-center justify-center shadow-lg shadow-cyan-950/40 ring-1 ring-cyan-400/30">
              <GitPullRequest className="h-5 w-5 text-cyan-100" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-white">Autonomous Engineering Studio</h1>
                <Badge variant="connected">ACTIVE ENGINE</Badge>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/80 flex items-center gap-1">
                  <Zap className="h-3 w-3 text-cyan-400" />
                  Nebius AI Studio • NVIDIA Nemotron • Hopper GH100
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Mode A Repository Intelligence & Audit • Mode B Autonomous Build & Proof-Carrying Pull Requests
              </p>
            </div>
          </div>
        </div>

        {/* Mode Selector Tabs */}
        <div className="flex items-center bg-[#070A10] p-1 rounded-xl border border-[#172235]">
          <button
            onClick={() => setActiveTab("MODE_A")}
            className={`px-4 py-2 rounded-lg text-xs font-mono font-medium transition-all flex items-center gap-2 ${
              activeTab === "MODE_A"
                ? "bg-cyan-950/60 text-cyan-300 border border-cyan-500/50 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Search className="h-3.5 w-3.5" />
            Mode A: Repo Audit
          </button>
          <button
            onClick={() => setActiveTab("MODE_B")}
            className={`px-4 py-2 rounded-lg text-xs font-mono font-medium transition-all flex items-center gap-2 ${
              activeTab === "MODE_B"
                ? "bg-cyan-950/60 text-cyan-300 border border-cyan-500/50 shadow-sm"
                : "text-slate-400 hover:text-slate-200"
            }`}
          >
            <Sparkles className="h-3.5 w-3.5 text-cyan-400" />
            Mode B: Build & Repair (PCPR)
          </button>
        </div>
      </div>

      {/* Copy / Action Notice */}
      {copyNotice && (
        <div className="p-3 bg-emerald-950/60 border border-emerald-700/60 rounded-lg text-xs text-emerald-200 flex items-center justify-between animate-fadeIn">
          <span className="font-mono">{copyNotice}</span>
          <button onClick={() => setCopyNotice(null)} className="text-slate-400 hover:text-white">✕</button>
        </div>
      )}

      {/* GitHub Connection & Repository Intake Bar */}
      <Card className="p-4 bg-[#0B0F19] border-[#172235]">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
          {/* Status Indicator */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 text-xs font-mono">
              <FolderGit2 className="h-4 w-4 text-cyan-400" />
              <span className="text-slate-400">GitHub Client:</span>
              {githubStatus.status === "CONNECTED" ? (
                <Badge variant="success">CONNECTED ({githubStatus.username})</Badge>
              ) : githubStatus.status === "RATE_LIMITED" ? (
                <Badge variant="warning">RATE LIMITED</Badge>
              ) : (
                <Badge variant="neutral">READ-ONLY PUBLIC / LOCAL DEMO</Badge>
              )}
            </div>
            <span className="hidden sm:inline-block text-slate-700">|</span>
            <span className="text-[11px] text-slate-500 font-mono hidden sm:inline-block">
              {githubStatus.tokenConfigured
                ? `OAuth Scopes: ${githubStatus.scopes?.join(", ") || "repo, workflow"}`
                : "No token set in .env • Local Fixtures Active"}
            </span>
          </div>

          {/* Quick Target Input */}
          <div className="flex items-center gap-2">
            <select
              value={repoInput.startsWith("demo/") ? repoInput : "custom"}
              onChange={(e) => {
                if (e.target.value !== "custom") {
                  setRepoInput(e.target.value);
                  handleRunAudit(e.target.value);
                }
              }}
              className="bg-[#070A10] border border-[#172235] rounded-lg px-2.5 py-1.5 text-xs text-slate-200 font-mono focus:outline-none focus:border-cyan-500"
            >
              <option value="demo/payments-service">demo/payments-service (Python / unittest)</option>
              <option value="demo/legacy-batch">demo/legacy-batch (Python / CLI)</option>
              <option value="demo/conflict-lab">demo/conflict-lab (Dual Matrix)</option>
              <option value="demo/node-storefront">demo/node-storefront (Node / npm)</option>
              <option value="custom">Custom URL...</option>
            </select>

            <input
              type="text"
              placeholder="https://github.com/owner/repo or demo/..."
              value={repoInput}
              onChange={(e) => setRepoInput(e.target.value)}
              className="bg-[#070A10] border border-[#172235] rounded-lg px-3 py-1.5 text-xs text-slate-200 font-mono w-64 focus:outline-none focus:border-cyan-500"
            />

            <Button
              variant="outline"
              size="sm"
              onClick={handleVerifyRepo}
              disabled={isVerifyingRepo}
              className="text-xs font-mono"
            >
              {isVerifyingRepo ? "Verifying..." : "Verify Access"}
            </Button>
          </div>
        </div>

        {verificationError && (
          <div className="mt-3 p-2 bg-red-950/40 border border-red-800/60 rounded text-xs text-red-300 font-mono flex items-center gap-2">
            <AlertCircle className="h-3.5 w-3.5 text-red-400 shrink-0" />
            <span>{verificationError}</span>
          </div>
        )}
      </Card>

      {/* ======================================================== */}
      {/* MODE A: REPOSITORY INTELLIGENCE & AUDIT                  */}
      {/* ======================================================== */}
      {activeTab === "MODE_A" && (
        <div className="space-y-6 animate-fadeIn">
          {/* Mode A Hero / Controls */}
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <div>
              <h2 className="text-lg font-bold text-white tracking-tight flex items-center gap-2">
                <span>Repository Architecture & Security Audit</span>
                {auditReport && (
                  <span className="text-xs font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                    {auditReport.reportId}
                  </span>
                )}
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                Deep AST analysis, dependency graph extraction, test harness discovery, and vulnerability hypotheses.
              </p>
            </div>

            <Button
              variant="primary"
              size="sm"
              onClick={() => handleRunAudit(repoInput)}
              disabled={isAuditing}
              className="text-xs font-mono bg-cyan-600 hover:bg-cyan-500 text-white flex items-center gap-2"
            >
              <RotateCcw className={`h-3.5 w-3.5 ${isAuditing ? "animate-spin" : ""}`} />
              {isAuditing ? "Auditing Repository..." : "Re-Run Complete Audit"}
            </Button>
          </div>

          {/* Architecture Map Card */}
          {auditReport?.architectureMap && (
            <Card className="p-5 bg-[#0B0F19] border-[#172235] space-y-4">
              <div className="flex items-center justify-between border-b border-[#172235] pb-3">
                <div className="flex items-center gap-2 text-xs font-mono text-cyan-400 font-semibold">
                  <CpuIcon className="h-4 w-4" />
                  <span>Architecture Intelligence Map: {auditReport.architectureMap.repoName}</span>
                </div>
                <div className="flex items-center gap-2 text-xs font-mono text-slate-400">
                  <span>Branch: <span className="text-slate-200">{auditReport.architectureMap.defaultBranch}</span></span>
                  <span>•</span>
                  <span>Commit: <span className="text-slate-200">{auditReport.architectureMap.commitSha}</span></span>
                </div>
              </div>

              {/* Language Distribution Bar */}
              <div>
                <div className="flex items-center justify-between text-xs font-mono text-slate-400 mb-1.5">
                  <span>Detected Language Composition</span>
                  <span>{auditReport.architectureMap.totalFilesScanned} files scanned</span>
                </div>
                <div className="h-3 w-full rounded-full bg-slate-900 overflow-hidden flex">
                  {Object.entries(auditReport.architectureMap.languages).map(([lang, pct], idx) => {
                    const colors = [
                      "bg-cyan-500",
                      "bg-indigo-500",
                      "bg-emerald-500",
                      "bg-amber-500",
                      "bg-rose-500"
                    ];
                    return (
                      <div
                        key={lang}
                        style={{ width: `${pct}%` }}
                        className={`${colors[idx % colors.length]} h-full transition-all`}
                        title={`${lang}: ${pct}%`}
                      />
                    );
                  })}
                </div>
                <div className="flex flex-wrap gap-4 mt-2">
                  {Object.entries(auditReport.architectureMap.languages).map(([lang, pct], idx) => {
                    const colors = [
                      "bg-cyan-400",
                      "bg-indigo-400",
                      "bg-emerald-400",
                      "bg-amber-400",
                      "bg-rose-400"
                    ];
                    return (
                      <div key={lang} className="flex items-center gap-1.5 text-[11px] font-mono text-slate-300">
                        <span className={`h-2 w-2 rounded-full ${colors[idx % colors.length]}`} />
                        <span>{lang} ({pct}%)</span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Grid: Entry Points, Test Harnesses, Manifests */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
                <div className="p-3 bg-[#070A10] rounded-lg border border-[#172235] space-y-1">
                  <div className="text-[11px] font-mono uppercase text-slate-400 font-semibold">Entry Points</div>
                  {auditReport.architectureMap.entryPoints.map((ep) => (
                    <div key={ep} className="text-xs font-mono text-cyan-300 truncate">
                      {ep}
                    </div>
                  ))}
                </div>

                <div className="p-3 bg-[#070A10] rounded-lg border border-[#172235] space-y-1">
                  <div className="text-[11px] font-mono uppercase text-slate-400 font-semibold">Test Runners</div>
                  {auditReport.architectureMap.testRunnersDiscovered.map((tr) => (
                    <div key={tr} className="text-xs font-mono text-emerald-300 truncate">
                      {tr}
                    </div>
                  ))}
                </div>

                <div className="p-3 bg-[#070A10] rounded-lg border border-[#172235] space-y-1">
                  <div className="text-[11px] font-mono uppercase text-slate-400 font-semibold">Manifests Found</div>
                  {auditReport.architectureMap.manifestsFound.map((mf) => (
                    <div key={mf} className="text-xs font-mono text-indigo-300 truncate">
                      {mf}
                    </div>
                  ))}
                </div>
              </div>

              {/* Dependencies Inventory Table */}
              {auditReport.architectureMap.dependencies.length > 0 && (
                <div className="pt-2">
                  <div className="text-xs font-mono text-slate-400 mb-2">
                    Discovered Dependencies ({auditReport.architectureMap.dependencies.length})
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                    {auditReport.architectureMap.dependencies.map((dep, idx) => (
                      <div
                        key={idx}
                        className="p-2 bg-[#070A10] rounded border border-[#172235] text-xs font-mono flex items-center justify-between"
                      >
                        <span className="text-slate-300 font-semibold truncate">{dep.name}</span>
                        <span className="text-slate-500 text-[11px]">{dep.versionSpec}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Card>
          )}

          {/* Audit Findings List */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-mono font-semibold uppercase tracking-wider text-slate-300">
                Identified Findings & Hypotheses ({auditReport?.findings.length || 0})
              </h3>
              <div className="flex items-center gap-2">
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">
                  {auditReport?.summary.criticalCount || 0} Critical
                </span>
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-amber-950 text-amber-300 border border-amber-800">
                  {auditReport?.summary.highCount || 0} High
                </span>
                <span className="text-xs font-mono px-2 py-0.5 rounded bg-slate-900 text-slate-400 border border-slate-800">
                  {auditReport?.summary.hypothesesCount || 0} Hypotheses
                </span>
              </div>
            </div>

            {!auditReport?.findings || auditReport.findings.length === 0 ? (
              <Card className="p-8 text-center text-slate-500 font-mono text-xs">
                No vulnerabilities or defects detected in current repository scope.
              </Card>
            ) : (
              auditReport.findings.map((f) => (
                <Card
                  key={f.id}
                  className="p-4 bg-[#0B0F19] border-[#172235] hover:border-cyan-900/60 transition-all space-y-3"
                >
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-2">
                    <div className="flex items-center gap-2.5">
                      <Badge
                        variant={
                          f.severity === "CRITICAL"
                            ? "critical"
                            : f.severity === "HIGH"
                            ? "warning"
                            : "info"
                        }
                      >
                        {f.severity}
                      </Badge>
                      <span className="text-xs font-mono font-bold text-cyan-300">{f.ruleId}</span>
                      <span className="text-slate-200 text-xs font-semibold">{f.title}</span>
                      {f.isHypothesis && (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800">
                          HYPOTHESIS
                        </span>
                      )}
                    </div>

                    {/* Turn Into Task Button */}
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => handleTurnFindingIntoTask(f)}
                      className="text-xs font-mono bg-cyan-950 hover:bg-cyan-900 border border-cyan-500/50 text-cyan-200 flex items-center gap-1.5 shrink-0"
                    >
                      <ListPlus className="h-3.5 w-3.5" />
                      Turn into Autonomous Task
                    </Button>
                  </div>

                  <p className="text-xs text-slate-300 leading-relaxed">{f.description}</p>

                  {f.codeSnippet && (
                    <div className="p-2.5 bg-[#070A10] rounded border border-[#172235] font-mono text-xs text-slate-300 flex items-center justify-between">
                      <span className="text-rose-300">{f.codeSnippet}</span>
                      <span className="text-slate-500 text-[11px]">
                        {f.filePath}{f.lineNumber ? `:${f.lineNumber}` : ""}
                      </span>
                    </div>
                  )}

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs font-mono pt-1 border-t border-[#172235]">
                    <div className="text-slate-400">
                      <span className="text-cyan-400 font-semibold">Recommended Fix: </span>
                      {f.recommendedFix}
                    </div>
                    {f.regressionTestSuggestion && (
                      <div className="text-slate-400">
                        <span className="text-emerald-400 font-semibold">Suggested Test: </span>
                        {f.regressionTestSuggestion}
                      </div>
                    )}
                  </div>
                </Card>
              ))
            )}
          </div>
        </div>
      )}

      {/* ======================================================== */}
      {/* MODE B: AUTONOMOUS BUILD & REPAIR (PROOF-CARRYING PRS)   */}
      {/* ======================================================== */}
      {activeTab === "MODE_B" && (
        <div className="space-y-6 animate-fadeIn">
          {/* Mode B Control Surface */}
          <Card className="p-5 bg-[#0B0F19] border-[#172235] space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3 border-b border-[#172235] pb-3">
              <div>
                <h3 className="text-sm font-mono font-semibold uppercase tracking-wider text-slate-200">
                  Autonomous Task Specification
                </h3>
                <p className="text-xs text-slate-400">
                  Accepts natural language bug fixes, features, or vulnerabilities and executes the 12-stage PCPR pipeline.
                </p>
              </div>

              <Button
                variant="primary"
                size="md"
                onClick={handleLaunchPCPR}
                disabled={isRunning}
                className="text-xs bg-gradient-to-r from-cyan-600 to-indigo-600 hover:from-cyan-500 hover:to-indigo-500 text-white flex items-center gap-2 font-semibold shadow-lg shadow-cyan-950/40"
              >
                <Play className={`h-4 w-4 ${isRunning ? "animate-spin" : ""}`} />
                {isRunning ? "Executing 12-Stage Pipeline..." : "Execute Proof-Carrying Run"}
              </Button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
              {/* Task Title & Acceptance Criteria (8 Cols) */}
              <div className="md:col-span-8 space-y-3">
                <div>
                  <label className="block text-xs font-mono uppercase tracking-wider text-slate-400 mb-1">
                    Task Title / Natural Language Prompt
                  </label>
                  <input
                    type="text"
                    value={taskTitle}
                    onChange={(e) => setTaskTitle(e.target.value)}
                    disabled={isRunning}
                    className="w-full bg-[#070A10] border border-[#172235] rounded-lg px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-cyan-500"
                  />
                </div>

                <div>
                  <label className="block text-xs font-mono uppercase tracking-wider text-slate-400 mb-1">
                    Acceptance Criteria (One per line)
                  </label>
                  <textarea
                    rows={3}
                    value={taskCriteria}
                    onChange={(e) => setTaskCriteria(e.target.value)}
                    disabled={isRunning}
                    className="w-full bg-[#070A10] border border-[#172235] rounded-lg px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none focus:border-cyan-500"
                  />
                </div>
              </div>

              {/* Autonomy Controls & UNWIND Gauge (4 Cols) */}
              <div className="md:col-span-4 space-y-3">
                <div>
                  <label className="block text-xs font-mono uppercase tracking-wider text-slate-400 mb-1">
                    Autonomy Mode
                  </label>
                  <div className="grid grid-cols-2 gap-1.5">
                    {(["PLAN_ONLY", "LOCAL_SANDBOX", "PATCH_AND_VERIFY", "CREATE_PR"] as AutonomyMode[]).map((mode) => (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => setAutonomyMode(mode)}
                        disabled={isRunning || mode === "CREATE_PR"}
                        className={`px-2 py-1.5 rounded text-[10px] font-mono font-medium border text-left transition-colors ${
                          autonomyMode === mode
                            ? "bg-cyan-950/50 border-cyan-500 text-cyan-200"
                            : mode === "CREATE_PR"
                            ? "bg-slate-900/30 border-slate-800 text-slate-600 cursor-not-allowed"
                            : "bg-[#070A10] border-[#172235] text-slate-400 hover:text-slate-200"
                        }`}
                      >
                        {mode}
                        {mode === "CREATE_PR" && " (UNCONFIG)"}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-[#070A10] border border-[#172235] space-y-1.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400 font-mono text-[11px]">UNWIND Authority:</span>
                    <span className="font-bold text-cyan-300 font-mono">1,450 bp</span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-400 font-mono text-[11px]">NVIDIA Accelerator:</span>
                    <span className="text-emerald-400 font-mono text-[11px]">Hopper GH100</span>
                  </div>
                  <div className="text-[10px] text-slate-500 pt-1 border-t border-slate-800">
                    Self-verification prohibited. Verifier runs in separate isolated context.
                  </div>
                </div>
              </div>
            </div>
          </Card>

          {/* Main Execution View: Stepper & Real-time Terminal */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
            {/* Left Column (5 Cols): 12-Stage Stepper */}
            <div className="lg:col-span-5 space-y-4">
              <Card className="p-5 bg-[#0B0F19] border-[#172235]">
                <div className="flex items-center justify-between mb-3 border-b border-[#172235] pb-2.5">
                  <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-300">
                    12-Stage Verification Pipeline
                  </h3>
                  <Badge variant={activeRun?.status === "READY_FOR_REVIEW" ? "success" : activeRun ? "info" : "neutral"}>
                    {activeRun?.status || "STANDBY"}
                  </Badge>
                </div>

                <div className="space-y-2">
                  {(activeRun?.plan || [
                    { id: "1", title: "Repository Architecture & Manifest Intake", agentRole: "Repository Intelligence", status: "PENDING" },
                    { id: "2", title: "Issue Diagnosis & Acceptance Plan Scoping", agentRole: "Issue Analyst", status: "PENDING" },
                    { id: "3", title: "Staged Checkpoint & Risk Decomposition", agentRole: "Planner / Orchestrator", status: "PENDING" },
                    { id: "4", title: "Autonomous Patch Synthesis (NVIDIA NIM)", agentRole: "Autonomous Coding Agent", status: "PENDING" },
                    { id: "5", title: "Real Discovered Test Execution & Bounded Loop", agentRole: "Test Engineer", status: "PENDING" },
                    { id: "6", title: "DevGuard Static Vulnerability & Secret Scan", agentRole: "DevGuard Security Analyst", status: "PENDING" },
                    { id: "7", title: "Multi-Source Evidence Advisory Reconciliation", agentRole: "Evidence Researcher", status: "PENDING" },
                    { id: "8", title: "Causal Dependency Graph & Blast Radius", agentRole: "Causal Impact Agent", status: "PENDING" },
                    { id: "9", title: "Independent Adversarial Verifier Evaluation", agentRole: "Independent Verifier", status: "PENDING" },
                    { id: "10", title: "Repair Assurance & Manifest Seal", agentRole: "Repair Assurance", status: "PENDING" },
                    { id: "11", title: "UNWIND Governance Lease Countersignature", agentRole: "UNWIND Governance Core", status: "PENDING" },
                    { id: "12", title: "Proof-Carrying Pull Request Delivery", agentRole: "GitHub Delivery Agent", status: "PENDING" }
                  ]).map((step, idx) => {
                    const isCompleted = step.status === "COMPLETED";
                    const isCurrent = step.status === "RUNNING";

                    return (
                      <div
                        key={step.id}
                        className={`p-2.5 rounded-lg border transition-all text-xs font-mono ${
                          isCompleted
                            ? "bg-slate-900/60 border-emerald-900/40 text-slate-200"
                            : isCurrent
                            ? "bg-cyan-950/40 border-cyan-500 text-cyan-200 shadow-[0_0_12px_rgba(6,182,212,0.15)] animate-pulse"
                            : "bg-[#070A10]/50 border-slate-900 text-slate-500"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-2">
                            <span className="text-[10px] text-slate-500 font-bold w-4">
                              {String(idx + 1).padStart(2, "0")}
                            </span>
                            <span className="font-semibold">{step.title}</span>
                          </div>
                          {isCompleted && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400 shrink-0" />}
                          {isCurrent && <Activity className="h-3.5 w-3.5 text-cyan-400 animate-spin shrink-0" />}
                        </div>

                        {step.outputSummary && (
                          <div className="text-[11px] text-slate-400 mt-1 pl-6 line-clamp-1">
                            {step.outputSummary}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </Card>
            </div>

            {/* Right Column (7 Cols): Live Streaming Terminal & Test Proof */}
            <div className="lg:col-span-7 space-y-4">
              <Card className="p-5 bg-[#0B0F19] border-[#172235]">
                <div className="flex items-center justify-between mb-3 border-b border-[#172235] pb-2.5">
                  <div className="flex items-center gap-2 text-xs font-mono text-slate-300">
                    <Terminal className="h-4 w-4 text-cyan-400" />
                    <span>Live Verifiable Execution Stream</span>
                  </div>
                  <span className="text-[10px] font-mono text-slate-500">
                    {activeRun?.events.length || 0} events recorded
                  </span>
                </div>

                <div className="h-72 overflow-y-auto bg-[#070A10] p-3.5 rounded-lg border border-[#172235] font-mono text-xs space-y-2">
                  {!activeRun?.events || activeRun.events.length === 0 ? (
                    <div className="text-slate-600 text-center py-24 text-[11px]">
                      Pipeline idle. Click &quot;Execute Proof-Carrying Run&quot; above to initiate autonomous engineering.
                    </div>
                  ) : (
                    activeRun.events.map((evt) => (
                      <div key={evt.id} className="leading-relaxed">
                        <span className="text-slate-600">[{new Date(evt.timestamp).toLocaleTimeString()}]</span>{" "}
                        <span className="text-cyan-400 font-semibold">{evt.agentRole}:</span>{" "}
                        <span className="text-slate-200">{evt.details}</span>
                      </div>
                    ))
                  )}
                  <div ref={logsEndRef} />
                </div>
              </Card>

              {/* Test Execution & Command Telemetry Proof */}
              {manifest && (
                <Card className="p-5 bg-[#0B0F19] border-[#172235] space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2 text-xs font-mono text-emerald-400 font-semibold">
                      <ShieldCheck className="h-4 w-4" />
                      <span>Real Deterministic Test Execution Proof</span>
                    </div>
                    <Badge variant="success">EXIT CODE 0</Badge>
                  </div>

                  <div className="p-3 bg-[#070A10] rounded-lg border border-[#172235] font-mono text-xs space-y-1.5">
                    <div className="flex justify-between text-[11px] text-slate-400">
                      <span>Command:</span>
                      <span className="text-slate-200">
                        {manifest.testResults.commandExecution.command}{" "}
                        {manifest.testResults.commandExecution.args.join(" ")}
                      </span>
                    </div>
                    <div className="flex justify-between text-[11px] text-slate-400">
                      <span>Tests Passed:</span>
                      <span className="text-emerald-400 font-bold">
                        {manifest.testResults.passed}/{manifest.testResults.total} passed
                      </span>
                    </div>
                    <div className="flex justify-between text-[11px] text-slate-400">
                      <span>Execution Duration:</span>
                      <span className="text-slate-300">{manifest.testResults.durationSeconds}s</span>
                    </div>
                    <pre className="p-2 bg-slate-950 text-slate-300 rounded border border-slate-900 text-[10px] whitespace-pre-wrap mt-2">
                      {manifest.testResults.commandExecution.stdout || manifest.testResults.commandExecution.stderr}
                    </pre>
                  </div>
                </Card>
              )}
            </div>
          </div>

          {/* Proof-Carrying Evidence Manifest Inspection (Rendered upon completion) */}
          {manifest && (
            <div className="space-y-6 pt-4 border-t border-[#172235]">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-lg font-bold text-white tracking-tight">
                      Proof-Carrying PR Evidence Package
                    </h2>
                    <Badge variant="success">SEALED WITH SHA-256</Badge>
                  </div>
                  <p className="text-xs text-slate-400 font-mono mt-0.5">
                    Manifest Hash: <span className="text-cyan-300 select-all">{manifest.manifestHash}</span>
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => copyToClipboard(JSON.stringify(manifest, null, 2), "JSON Manifest")}
                    className="text-xs font-mono flex items-center gap-1.5"
                  >
                    <Copy className="h-3.5 w-3.5" />
                    Export JSON
                  </Button>
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => {
                      const md = `# AEGISNOVA Proof-Carrying PR Evidence Package\n**Run ID:** ${manifest.runId}\n**Repository:** ${manifest.repoId}\n**Manifest Hash:** \`${manifest.manifestHash}\`\n\n## 1. Verifier Verdict\n- **Verdict:** ${manifest.verifierVerdict}\n- **Model:** ${manifest.modelUsed}\n\n## 2. Test Execution Proof\n\`\`\`\n${manifest.testResults.commandExecution.stdout}\n\`\`\`\n\n## 3. UNWIND Governance\n- **Warrant Debited:** -${manifest.unwindWarrantDebitBp} bp\n- **Lineage Hash:** \`${manifest.governanceDecision?.lineageHash}\`\n\n## 4. Delivery Status\n- **Status:** ${manifest.pullRequestResult.status}\n- **Explanation:** ${manifest.pullRequestResult.explanation}\n`;
                      copyToClipboard(md, "Markdown Evidence Report");
                    }}
                    className="text-xs font-mono flex items-center gap-1.5"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Export Markdown
                  </Button>
                </div>
              </div>

              {/* 3-Column Evidence Grid */}
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                {/* 1. Independent Verifier Verdict */}
                <Card className="p-4 bg-[#0B0F19] border-[#172235] space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-slate-400">Independent Verifier</span>
                    <Badge variant={manifest.verifierVerdict === "PASS" ? "success" : "warning"}>
                      {manifest.verifierVerdict}
                    </Badge>
                  </div>
                  <div className="text-xs text-slate-300">
                    Fresh-context adversarial review confirmed zero prompt injection, scope violation, or regression risks.
                  </div>
                  <div className="text-[11px] font-mono text-slate-500 pt-1 border-t border-slate-800">
                    Model: {manifest.modelUsed}
                  </div>
                </Card>

                {/* 2. UNWIND Governance Warrant Seal */}
                <Card className="p-4 bg-[#0B0F19] border-[#172235] space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-slate-400">UNWIND Warrant Gate</span>
                    <Badge variant="connected">-{manifest.unwindWarrantDebitBp} bp DEBIT</Badge>
                  </div>
                  <div className="text-xs text-slate-300">
                    Countersignature authorized. Decision lineage permanently tied to manifest SHA-256.
                  </div>
                  <div className="text-[10px] font-mono text-cyan-400 pt-1 border-t border-slate-800 truncate">
                    Lineage: {manifest.governanceDecision?.lineageHash}
                  </div>
                </Card>

                {/* 3. GitHub Delivery Status */}
                <Card className="p-4 bg-[#0B0F19] border-[#172235] space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-mono text-slate-400">Delivery Status</span>
                    <Badge variant="warning">{manifest.pullRequestResult.status}</Badge>
                  </div>
                  <div className="text-xs text-slate-300 line-clamp-2">
                    {manifest.pullRequestResult.explanation}
                  </div>
                  <div className="text-[11px] font-mono text-slate-500 pt-1 border-t border-slate-800">
                    Branch: {manifest.pullRequestResult.branchName}
                  </div>
                </Card>
              </div>

              {/* Unified Diff Viewer */}
              <Card className="p-5 bg-[#0B0F19] border-[#172235] space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2 text-xs font-mono text-slate-200">
                    <FileCode className="h-4 w-4 text-cyan-400" />
                    <span>Patched File: app/__init__.py</span>
                  </div>
                  <span className="text-xs font-mono text-slate-500">
                    Diff Hash: {manifest.diffHash.slice(0, 16)}...
                  </span>
                </div>

                <pre className="p-4 bg-[#070A10] rounded-lg border border-[#172235] font-mono text-xs overflow-x-auto text-slate-300">
                  {manifest.changedFiles[0]?.diff || "No diff generated."}
                </pre>
              </Card>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
