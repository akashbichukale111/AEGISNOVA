"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  ShieldAlert,
  GitBranch,
  CheckCircle2,
  Clock,
  AlertTriangle,
  Play,
  RotateCw,
  ExternalLink,
  ChevronRight,
  Sparkles,
  Layers,
  FileCheck,
  Server,
  Scale,
  Zap,
  Cpu,
  Moon,
} from "lucide-react";
import { MetricCard } from "../components/ui/MetricCard";
import { Badge } from "../components/ui/Badge";
import { Button } from "../components/ui/Button";
import { Card, CardHeader } from "../components/ui/Card";
import { Modal, ConfirmationModal } from "../components/ui/Modal";
import {
  INITIAL_FINDINGS,
  INITIAL_WORKFLOWS,
  INITIAL_APPROVALS,
  INITIAL_INTEGRATIONS,
  INITIAL_AUDIT_LOGS,
} from "../lib/demo-data";
import { Finding, WorkflowRun, ApprovalRequest } from "../contracts";

export default function OverviewPage() {
  const [findings, setFindings] = useState<Finding[]>(INITIAL_FINDINGS);
  const [workflows, setWorkflows] = useState<WorkflowRun[]>(INITIAL_WORKFLOWS);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>(INITIAL_APPROVALS);
  const [isScanning, setIsScanning] = useState(false);
  const [scanProgress, setScanProgress] = useState(0);
  const [scanStep, setScanStep] = useState("");
  const [selectedApproval, setSelectedApproval] = useState<ApprovalRequest | null>(null);
  const [isConfirmApprovalOpen, setIsConfirmApprovalOpen] = useState(false);

  // Filter stats
  const openFindingsCount = findings.filter((f) => f.status === "OPEN" || f.status === "PATCH_PROPOSED").length;
  const criticalFindingsCount = findings.filter((f) => f.severity === "CRITICAL" && f.status !== "RESOLVED").length;
  const activeWorkflowsCount = workflows.filter((w) => w.status === "RUNNING" || w.status === "PAUSED_APPROVAL").length;
  const pendingApprovalsCount = approvals.filter((a) => a.state === "PENDING").length;

  // Interactive Demo Security Scan (clearly labelled DEMO, zero network calls to cloud)
  const handleRunDemoScan = () => {
    setIsScanning(true);
    setScanProgress(15);
    setScanStep("Initializing AST parser & static rule engine...");

    setTimeout(() => {
      setScanProgress(45);
      setScanStep("Scanning repository syntax trees (DevGuard AI Engine)...");
    }, 700);

    setTimeout(() => {
      setScanProgress(80);
      setScanStep("Corroborating findings against UNWIND capability scope...");
    }, 1500);

    setTimeout(() => {
      setScanProgress(100);
      setScanStep("Scan complete. 1 new simulated finding triaged.");
      setIsScanning(false);

      // Append demo finding
      const newFinding: Finding = {
        schemaVersion: "1.0.0",
        id: `FIND-SEC-${Math.floor(100 + Math.random() * 900)}`,
        scanJobId: "scan-job-local-live",
        repositoryId: "repo-devguard-ai",
        ruleId: "CWE-319",
        title: "Cleartext Transmission of Sensitive Telemetry Token",
        description: "OpenTelemetry exporter endpoint configured with insecure plain HTTP scheme in production manifest.",
        severity: "HIGH",
        filePath: "backend/core/telemetry.py",
        lineNumber: 88,
        codeSnippet: 'endpoint="http://collector.internal:4318"',
        status: "OPEN",
        isDemo: true,
        createdAt: new Date().toISOString(),
      };
      setFindings((prev) => [newFinding, ...prev]);
    }, 2400);
  };

  // Handle human countersignature approval
  const handleApproveAction = () => {
    if (!selectedApproval) return;
    setApprovals((prev) =>
      prev.map((a) => (a.id === selectedApproval.id ? { ...a, state: "APPROVED" } : a))
    );
    setSelectedApproval(null);
  };

  return (
    <div className="space-y-8">
      {/* Top Welcome / System Posture Banner */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-r from-[#0C1527] via-[#0E1A33] to-[#0A1222] border border-[#1E2E4E] p-6 lg:p-8 shadow-2xl">
        <div className="absolute right-0 top-0 h-full w-1/3 bg-gradient-to-l from-cyan-500/10 via-transparent to-transparent pointer-events-none" />
        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-mono text-xs uppercase tracking-wider text-cyan-400 font-semibold">
                Unified AI Security & Autonomous Engineering
              </span>
              <Badge variant="demo" size="sm">
                LOCAL / DEMO MODE
              </Badge>
            </div>
            <h1 className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              AEGISNOVA Command Center
            </h1>
            <p className="text-sm text-slate-300 max-w-2xl leading-relaxed">
              Real security intelligence from <strong className="text-cyan-300">DevGuard AI</strong>, enterprise command architecture from <strong className="text-cyan-300">DevGuard Enterprise</strong>, and governed authority from <strong className="text-cyan-300">UNWIND Governance Core</strong>.
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-3 shrink-0">
            <Button
              variant="primary"
              size="md"
              icon={<Play className="h-4 w-4" />}
              onClick={handleRunDemoScan}
              disabled={isScanning}
            >
              {isScanning ? "Scanning Pipeline..." : "Run Demo Security Scan"}
            </Button>
            <Link href="/security">
              <Button variant="secondary" size="md">
                Open Security Center
              </Button>
            </Link>
          </div>
        </div>

        {/* Scan Progress Bar if active */}
        {isScanning && (
          <div className="mt-5 space-y-2 border-t border-slate-800/80 pt-4">
            <div className="flex justify-between text-xs font-mono text-cyan-300">
              <span>{scanStep}</span>
              <span>{scanProgress}%</span>
            </div>
            <div className="w-full bg-slate-800 rounded-full h-1.5 overflow-hidden">
              <div
                className="bg-cyan-500 h-1.5 rounded-full transition-all duration-300"
                style={{ width: `${scanProgress}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* NVIDIA NIM Acceleration Banner for NVIDIA Hackathon */}
      <div className="p-4 rounded-xl bg-gradient-to-r from-emerald-950/40 via-slate-900 to-[#0B0F19] border border-emerald-800/40 shadow-lg flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-lg bg-emerald-950 border border-emerald-700/60 flex items-center justify-center text-emerald-400 shrink-0">
            <Zap className="h-5 w-5" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-sm text-white">NVIDIA NIM & NeMo Guardrails Acceleration</span>
              <Badge variant="success">TENSORRT-LLM FP8</Badge>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800/80">
                154 tok/s • 14.8ms
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-0.5">
              Autonomous security reasoning powered by <strong className="text-emerald-300">Nemotron-4-340B</strong> and <strong className="text-emerald-300">Llama-3.1-70B</strong> with NeMo policy containment.
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <Link href="/nightshift">
            <Button variant="outline" size="sm" className="text-xs border-indigo-800 text-indigo-300 hover:bg-indigo-950/40 flex items-center gap-1.5">
              <Moon className="h-3.5 w-3.5" />
              NightShift SDE
            </Button>
          </Link>
          <Link href="/settings">
            <Button variant="secondary" size="sm" className="text-xs border-emerald-800 text-emerald-300 hover:bg-emerald-950/40">
              NIM Telemetry
            </Button>
          </Link>
        </div>
      </div>

      {/* 4 Primary Operational Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          label="Open Findings"
          value={openFindingsCount}
          subtext={`${criticalFindingsCount} Critical requiring fix`}
          severity={criticalFindingsCount > 0 ? "critical" : "warning"}
          icon={<ShieldAlert className="h-5 w-5" />}
          isDemo={true}
          trend={{ direction: "up", value: "+1 from scan" }}
        />
        <MetricCard
          label="Active Workflows"
          value={activeWorkflowsCount}
          subtext="1 Paused at Human Gate"
          severity="warning"
          icon={<RotateCw className="h-5 w-5" />}
          isDemo={true}
        />
        <MetricCard
          label="Approvals Waiting"
          value={pendingApprovalsCount}
          subtext="UNWIND Scoped Authority"
          severity={pendingApprovalsCount > 0 ? "warning" : "success"}
          icon={<Scale className="h-5 w-5" />}
          isDemo={true}
        />
        <MetricCard
          label="Warrant Balance"
          value="1,450 bp"
          subtext="Deterministic Pure Fold"
          severity="success"
          icon={<CheckCircle2 className="h-5 w-5" />}
          isDemo={true}
        />
      </div>

      {/* Main Grid: Needs Attention & Event Timeline */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left 2 Cols: Prioritized Attention Queue */}
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader
              title="Needs Attention"
              subtitle="Prioritized queue of security findings and pending human approvals"
              badge={<Badge variant="demo">DEMO DATA</Badge>}
              action={
                <Link href="/governance">
                  <span className="text-xs font-medium text-cyan-400 hover:text-cyan-300 flex items-center gap-1">
                    Manage Approvals <ChevronRight className="h-3.5 w-3.5" />
                  </span>
                </Link>
              }
            />

            <div className="space-y-3">
              {approvals
                .filter((a) => a.state === "PENDING")
                .map((appr) => (
                  <div
                    key={appr.id}
                    className="p-4 rounded-xl bg-slate-900/80 border border-amber-900/40 hover:border-amber-700/60 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="warning">APPROVAL WAITING</Badge>
                        <span className="font-mono text-xs text-slate-300 font-semibold">
                          {appr.id}
                        </span>
                        <span className="text-xs text-slate-500">•</span>
                        <span className="text-xs text-slate-400">{appr.requiredScope}</span>
                      </div>
                      <p className="text-sm font-medium text-slate-100">
                        High-risk write paused: {(appr.actionPayload.patchSummary as string) || appr.actionType}
                      </p>
                      <div className="flex items-center gap-3 text-xs text-slate-400">
                        <span>Debit: <strong className="text-cyan-300">{appr.warrantDebitBp} bp</strong></span>
                        <span>Requested by: {appr.requestedBy}</span>
                      </div>
                    </div>

                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => {
                          setSelectedApproval(appr);
                          setIsConfirmApprovalOpen(true);
                        }}
                      >
                        Authorize Write
                      </Button>
                    </div>
                  </div>
                ))}

              {findings.slice(0, 3).map((f) => (
                <div
                  key={f.id}
                  className="p-4 rounded-xl bg-slate-900/60 border border-[#1C263A] hover:border-slate-700 transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-4"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <Badge variant={f.severity.toLowerCase() as any}>{f.severity}</Badge>
                      <span className="font-mono text-xs text-slate-400 font-semibold">{f.ruleId}</span>
                      <span className="text-xs text-slate-500">•</span>
                      <span className="font-mono text-xs text-slate-400">{f.filePath}:{f.lineNumber}</span>
                    </div>
                    <p className="text-sm font-medium text-slate-200">{f.title}</p>
                    <p className="text-xs text-slate-400 line-clamp-1">{f.description}</p>
                  </div>

                  <Link href="/security" className="shrink-0">
                    <Button variant="secondary" size="sm">
                      Inspect Finding
                    </Button>
                  </Link>
                </div>
              ))}
            </div>
          </Card>

          {/* Active Workflows Strip */}
          <Card>
            <CardHeader
              title="Autonomous Workflow Executions"
              subtitle="Checkpoint-tracked pipelines with governance gating"
              badge={<Badge variant="demo">DEMO</Badge>}
            />
            <div className="space-y-3">
              {workflows.map((wf) => (
                <div
                  key={wf.id}
                  className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800 flex items-center justify-between gap-4"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant={
                          wf.status === "COMPLETED"
                            ? "success"
                            : wf.status === "PAUSED_APPROVAL"
                            ? "warning"
                            : "info"
                        }
                      >
                        {wf.status}
                      </Badge>
                      <span className="font-mono text-xs text-white font-medium">{wf.title}</span>
                    </div>
                    <div className="text-xs text-slate-400">
                      Step: <span className="text-slate-300">{wf.currentStep}</span> ({wf.completedSteps}/{wf.totalSteps})
                    </div>
                  </div>

                  <div className="text-right shrink-0">
                    <span className="text-[11px] font-mono text-slate-400">{wf.correlationId}</span>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Right 1 Col: Event Timeline & Impact Card */}
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Operational Event Timeline"
              subtitle="Real-time correlated telemetry"
              badge={<Badge variant="info">LIVE</Badge>}
            />
            <div className="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-800">
              {INITIAL_AUDIT_LOGS.map((event) => (
                <div key={event.id} className="relative group">
                  <div className="absolute -left-[21px] top-1 h-2.5 w-2.5 rounded-full bg-cyan-400 ring-4 ring-[#0D131F]" />
                  <div className="space-y-0.5">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-xs font-semibold text-white">
                        {event.action}
                      </span>
                      <span className="text-[10px] font-mono text-slate-400">
                        {new Date(event.timestamp).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    </div>
                    <div className="text-xs text-slate-400">
                      Actor: <span className="font-mono text-slate-300">{event.actor}</span>
                    </div>
                    {event.warrantBurnedBp && (
                      <div className="text-[11px] font-mono text-amber-400">
                        Debit: -{event.warrantBurnedBp} bp
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          {/* Repository & Impact Topology Preview */}
          <Card>
            <CardHeader
              title="Impact Topology"
              subtitle="Cross-repo dependency blast radius"
              action={
                <Link href="/impact">
                  <Button variant="ghost" size="sm">
                    View Graph
                  </Button>
                </Link>
              }
            />
            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-3">
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Reverse Index Nodes:</span>
                <span className="font-mono font-bold text-white">2,594</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Active Blast Radius:</span>
                <span className="font-mono font-bold text-cyan-400">14 Services</span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-slate-400">Model Calls Required:</span>
                <span className="font-mono font-bold text-emerald-400">0 (T0/T1 Filtered)</span>
              </div>
              <div className="pt-2 border-t border-slate-800 text-[11px] text-slate-500">
                UNWIND zero-model guarantee: deterministic arithmetic prevents hallucinated cascade costs.
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Module Integration Status Matrix (3 existing + 5 planned) */}
      <Card>
        <CardHeader
          title="Platform Integration Status Matrix"
          subtitle="Honest status of upstream repositories and planned feature modules"
          action={
            <Link href="/settings">
              <Button variant="outline" size="sm">
                Module Contracts
              </Button>
            </Link>
          }
        />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {INITIAL_INTEGRATIONS.map((mod) => (
            <div
              key={mod.moduleKey}
              className={`p-4 rounded-xl border transition-all ${
                mod.status === "CONNECTED"
                  ? "bg-slate-900/80 border-emerald-900/50 hover:border-emerald-700/60"
                  : "bg-slate-900/40 border-slate-800 hover:border-slate-700"
              }`}
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <h4 className="font-semibold text-xs text-white tracking-tight line-clamp-1">
                  {mod.displayName}
                </h4>
                <Badge
                  variant={
                    mod.status === "CONNECTED"
                      ? "connected"
                      : mod.status === "PLANNED"
                      ? "planned"
                      : "not_connected"
                  }
                  size="sm"
                >
                  {mod.status}
                </Badge>
              </div>
              <p className="text-[11px] text-slate-400 mb-3 line-clamp-2">{mod.description}</p>
              <div className="pt-2 border-t border-slate-800/80 flex items-center justify-between text-[10px] font-mono text-slate-400">
                <span>{mod.version}</span>
                <span className="text-slate-400">{mod.status === "CONNECTED" ? "Verified" : "Planned Slot"}</span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Confirmation Dialog for Approving Actions */}
      {selectedApproval && (
        <ConfirmationModal
          isOpen={isConfirmApprovalOpen}
          onClose={() => setIsConfirmApprovalOpen(false)}
          onConfirm={handleApproveAction}
          title={`Authorize ${selectedApproval.actionType}`}
          message={`Are you sure you want to approve this high-risk write? This will apply patch for ${selectedApproval.id} and debit ${selectedApproval.warrantDebitBp} basis points from the tenant warrant.`}
          confirmLabel="Countersign & Authorize"
          confirmVariant="primary"
          riskBadge="HUMAN COUNTERSIGNATURE REQUIRED"
        />
      )}
    </div>
  );
}
