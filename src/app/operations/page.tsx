"use client";

import React, { useState, useEffect } from "react";
import {
  Bot,
  RotateCw,
  Clock,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Play,
  Search,
  Filter,
  Layers,
  Bell,
  Scale,
  Activity,
  Terminal,
  ShieldCheck,
  ChevronRight,
  RefreshCw,
  Send,
  Radio,
  Sliders,
  ExternalLink,
} from "lucide-react";
import { Card, CardHeader } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Modal, ConfirmationModal } from "../../components/ui/Modal";
import { MetricCard } from "../../components/ui/MetricCard";
import {
  WorkflowRun,
  NotificationStatus,
  ApprovalRequest,
  DeadLetterItem,
  OperationalAlarm,
  WorkflowTimelineEvent,
} from "../../contracts";

export default function OperationsCenterPage() {
  const [activeTab, setActiveTab] = useState<
    | "overview"
    | "workflows"
    | "approvals"
    | "notifications"
    | "queues"
    | "reliability"
    | "events"
    | "integrations"
  >("overview");

  // Live Service State
  const [serviceOnline, setServiceOnline] = useState<boolean | null>(null);
  const [isConnecting, setIsConnecting] = useState(false);
  const [lastCheckTime, setLastCheckTime] = useState<string>("");

  // Data states
  const [overviewData, setOverviewData] = useState<any>(null);
  const [workflows, setWorkflows] = useState<WorkflowRun[]>([]);
  const [approvals, setApprovals] = useState<ApprovalRequest[]>([]);
  const [notifications, setNotifications] = useState<NotificationStatus[]>([]);
  const [dlqItems, setDlqItems] = useState<DeadLetterItem[]>([]);
  const [alarms, setAlarms] = useState<OperationalAlarm[]>([]);
  const [events, setEvents] = useState<WorkflowTimelineEvent[]>([]);

  // Modals & User actions
  const [selectedRun, setSelectedRun] = useState<WorkflowRun | null>(null);
  const [selectedTimeline, setSelectedTimeline] = useState<any[]>([]);
  const [isStartModalOpen, setIsStartModalOpen] = useState(false);
  const [startRequiresApproval, setStartRequiresApproval] = useState(true);
  const [startWorkflowType, setStartWorkflowType] = useState("sample.governed_action");
  const [confirmCancelRunId, setConfirmCancelRunId] = useState<string | null>(null);
  const [confirmRedriveId, setConfirmRedriveId] = useState<string | null>(null);

  // Approval decision state
  const [decisionModalApproval, setDecisionModalApproval] = useState<ApprovalRequest | null>(null);
  const [decisionChoice, setDecisionChoice] = useState<"granted" | "rejected">("granted");

  // Fetch status and data from local Next.js proxy
  const fetchOperationsData = async () => {
    setIsConnecting(true);
    try {
      const healthRes = await fetch("/api/operations/health");
      if (healthRes.ok) {
        setServiceOnline(true);
        setLastCheckTime(new Date().toLocaleTimeString());

        // Fetch overview
        const ovRes = await fetch("/api/operations/overview");
        if (ovRes.ok) {
          const ov = await ovRes.json();
          setOverviewData(ov);
        }

        // Fetch runs
        const runsRes = await fetch("/api/operations/runs");
        if (runsRes.ok) {
          const r = await runsRes.json();
          setWorkflows(r.items || []);
        }

        // Fetch approvals
        const apprRes = await fetch("/api/operations/approvals");
        if (apprRes.ok) {
          const a = await apprRes.json();
          setApprovals(a.items || []);
        }

        // Fetch notifications
        const notifRes = await fetch("/api/operations/notifications");
        if (notifRes.ok) {
          const n = await notifRes.json();
          setNotifications(n.items || []);
        }

        // Fetch DLQ
        const dlqRes = await fetch("/api/operations/dlq");
        if (dlqRes.ok) {
          const d = await dlqRes.json();
          setDlqItems(d.items || []);
        }

        // Fetch Alarms
        const alarmRes = await fetch("/api/operations/alarms");
        if (alarmRes.ok) {
          const al = await alarmRes.json();
          setAlarms(al.items || []);
        }

        // Fetch Events
        const evRes = await fetch("/api/operations/events");
        if (evRes.ok) {
          const ev = await evRes.json();
          setEvents(ev.items || []);
        }
      } else {
        setServiceOnline(false);
      }
    } catch (e) {
      setServiceOnline(false);
    } finally {
      setIsConnecting(false);
    }
  };

  useEffect(() => {
    fetchOperationsData();
    const interval = setInterval(fetchOperationsData, 8000);
    return () => clearInterval(interval);
  }, []);

  // Inspect run detail and timeline
  const inspectRun = async (run: WorkflowRun) => {
    setSelectedRun(run);
    try {
      const res = await fetch(`/api/operations/runs/${run.id}`);
      if (res.ok) {
        const detail = await res.json();
        setSelectedTimeline(detail.timeline || []);
      }
    } catch {
      setSelectedTimeline([]);
    }
  };

  // Start new sample workflow
  const handleStartWorkflow = async () => {
    setIsStartModalOpen(false);
    try {
      const res = await fetch("/api/operations/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          workflow_type: startWorkflowType,
          payload: {
            approval_required: startRequiresApproval,
            action: "record_marker",
            scope: "scope:ops:execute",
            risk_level: "high",
            notify: {
              channel: "local_sink",
              destination: "ops-lead@aegisnova.local",
            },
          },
        }),
      });
      if (res.ok) {
        fetchOperationsData();
      }
    } catch (err) {
      console.error(err);
    }
  };

  // Cancel workflow
  const handleCancelRun = async () => {
    if (!confirmCancelRunId) return;
    try {
      await fetch(`/api/operations/runs/${confirmCancelRunId}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Cancelled by AEGISNOVA operator" }),
      });
      fetchOperationsData();
    } finally {
      setConfirmCancelRunId(null);
    }
  };

  // Submit test dev-decision
  const handleSubmitDevDecision = async () => {
    if (!decisionModalApproval) return;
    try {
      await fetch(`/api/operations/approvals/${decisionModalApproval.id}/dev-decision`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision: decisionChoice }),
      });
      fetchOperationsData();
    } finally {
      setDecisionModalApproval(null);
    }
  };

  // Redrive single DLQ message
  const handleRedrive = async () => {
    if (!confirmRedriveId) return;
    try {
      await fetch("/api/operations/dlq/redrive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: [confirmRedriveId], confirm: true }),
      });
      fetchOperationsData();
    } finally {
      setConfirmRedriveId(null);
    }
  };

  // Trigger worker tick
  const handleWorkerTick = async () => {
    await fetch("/api/operations/worker/tick", { method: "POST" });
    fetchOperationsData();
  };

  return (
    <div className="space-y-6">
      {/* Header & Connection Indicator */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-white tracking-tight">Operations Center</h1>
            <Badge variant="connected">WORKSTREAM 05 INTEGRATED</Badge>
            {serviceOnline === true ? (
              <Badge variant="success">LOCAL SERVICE CONNECTED</Badge>
            ) : serviceOnline === false ? (
              <Badge variant="warning">SERVICE OFFLINE</Badge>
            ) : (
              <Badge variant="neutral">CONNECTING...</Badge>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-1">
            Autonomous repository engineering, durable state machines, dead-letter queues, and governed alerts
          </p>
        </div>

        <div className="flex items-center gap-2.5">
          <Button
            variant="outline"
            size="sm"
            icon={<RefreshCw className={`h-3.5 w-3.5 ${isConnecting ? "animate-spin" : ""}`} />}
            onClick={fetchOperationsData}
            disabled={isConnecting}
          >
            Refresh
          </Button>
          <Button
            variant="primary"
            size="sm"
            icon={<Play className="h-3.5 w-3.5" />}
            onClick={() => setIsStartModalOpen(true)}
          >
            Start Local Workflow
          </Button>
        </div>
      </div>

      {/* Service Offline Guidance Banner */}
      {serviceOnline === false && (
        <Card className="border-amber-800/60 bg-amber-950/20 p-4">
          <div className="flex items-start gap-3">
            <AlertTriangle className="h-5 w-5 text-amber-400 shrink-0 mt-0.5" />
            <div className="space-y-1 text-xs">
              <h4 className="font-semibold text-white">Autonomous Operations Python Service Offline</h4>
              <p className="text-slate-300">
                The local Python background service is not running on <code>http://127.0.0.1:8080</code>. The AEGISNOVA product shell is operating in resilient fallback mode.
              </p>
              <div className="p-2.5 rounded bg-black/60 border border-slate-800 font-mono text-[11px] text-cyan-300 mt-2">
                cd d:\AEGISNOVA\services\autonomous-operations && python -m aegisnova_ops
              </div>
            </div>
          </div>
        </Card>
      )}

      {/* 8-Section Sub-Navigation Tabs */}
      <div className="flex items-center gap-1 overflow-x-auto border-b border-slate-800 pb-2 scrollbar-none text-xs font-medium">
        {[
          { id: "overview", label: "Overview" },
          { id: "workflows", label: `Workflow Runs (${workflows.length})` },
          { id: "approvals", label: `Approval Inbox (${approvals.filter((a) => a.state === "PENDING" || (a as any).status === "waiting_approval").length})` },
          { id: "notifications", label: `Notifications (${notifications.length})` },
          { id: "queues", label: `Queues & DLQ (${dlqItems.length})` },
          { id: "reliability", label: "Reliability & Alerts" },
          { id: "events", label: "Event Log" },
          { id: "integrations", label: "Provider Integrations" },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id as any)}
            className={`px-3 py-1.5 rounded-lg whitespace-nowrap transition-colors ${
              activeTab === tab.id
                ? "bg-cyan-950 text-cyan-200 border border-cyan-700/60 font-semibold"
                : "text-slate-400 hover:text-white hover:bg-slate-900"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* ----------------- TAB 1: OVERVIEW ----------------- */}
      {activeTab === "overview" && (
        <div className="space-y-6">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <MetricCard
              label="Active Workflows"
              value={workflows.filter((w) => w.status === "RUNNING" || (w.status as any) === "running").length}
              subtext="Durable State Machine"
              icon={<Bot className="h-5 w-5" />}
              severity="normal"
            />
            <MetricCard
              label="Approval Gates"
              value={approvals.filter((a) => a.state === "PENDING" || (a as any).status === "waiting_approval").length}
              subtext="UNWIND Fail-Closed Scope"
              icon={<Scale className="h-5 w-5" />}
              severity="warning"
            />
            <MetricCard
              label="Dead-Letter Queue"
              value={dlqItems.length}
              subtext="Exhausted Retries"
              icon={<AlertTriangle className="h-5 w-5" />}
              severity={dlqItems.length > 0 ? "critical" : "normal"}
            />
            <MetricCard
              label="Worker Heartbeat"
              value={serviceOnline ? "Online" : "Offline"}
              subtext={lastCheckTime ? `Last tick: ${lastCheckTime}` : "No connection"}
              icon={<Activity className="h-5 w-5" />}
              severity={serviceOnline ? "success" : "critical"}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2 space-y-4">
              <Card>
                <CardHeader
                  title="Recent Operational Runs"
                  subtitle="Latest state machine transitions and execution steps"
                  action={
                    <Button variant="ghost" size="sm" onClick={() => setActiveTab("workflows")}>
                      View All
                    </Button>
                  }
                />
                <div className="space-y-2.5">
                  {workflows.length === 0 ? (
                    <div className="p-8 text-center text-xs text-slate-500 font-mono">
                      No workflows currently recorded. Click "Start Local Workflow" above to initiate a run.
                    </div>
                  ) : (
                    workflows.slice(0, 4).map((w) => (
                      <div
                        key={w.id}
                        onClick={() => inspectRun(w)}
                        className="p-3.5 rounded-xl bg-slate-900/60 border border-slate-800/80 hover:border-slate-700 cursor-pointer flex items-center justify-between gap-4 transition-all"
                      >
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <Badge
                              variant={
                                w.status === "COMPLETED" || (w.status as any) === "completed"
                                  ? "success"
                                  : (w.status as any) === "waiting_approval" || w.status === "PAUSED_APPROVAL"
                                  ? "warning"
                                  : w.status === "FAILED" || (w.status as any) === "failed"
                                  ? "critical"
                                  : "info"
                              }
                            >
                              {w.status}
                            </Badge>
                            <span className="font-mono text-xs text-white font-semibold">{w.id}</span>
                            <span className="text-xs text-slate-500">•</span>
                            <span className="text-xs text-slate-400">{w.workflowType || (w as any).workflow_type}</span>
                          </div>
                          <div className="text-xs text-slate-300">
                            Current Step: <span className="font-mono text-cyan-300">{w.currentStep || (w as any).step}</span>
                          </div>
                        </div>
                        <ChevronRight className="h-4 w-4 text-slate-600" />
                      </div>
                    ))
                  )}
                </div>
              </Card>
            </div>

            <div className="space-y-4">
              <Card>
                <CardHeader title="Provider Integrations Status" subtitle="Multi-channel notification sinks" />
                <div className="space-y-3 text-xs font-mono">
                  <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-between">
                    <div>
                      <div className="text-white font-semibold">Local Outbox Sink</div>
                      <div className="text-slate-500 text-[10px]">Deterministic SQLite store</div>
                    </div>
                    <Badge variant="connected">LOCAL</Badge>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-between">
                    <div>
                      <div className="text-white font-semibold">Amazon SNS (Email/SMS)</div>
                      <div className="text-slate-500 text-[10px]">Unconfigured; fakes used</div>
                    </div>
                    <Badge variant="planned">UNCONFIGURED</Badge>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-between">
                    <div>
                      <div className="text-white font-semibold">Meta WhatsApp Cloud API</div>
                      <div className="text-slate-500 text-[10px]">Requires verified token</div>
                    </div>
                    <Badge variant="planned">UNCONFIGURED</Badge>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 flex items-center justify-between">
                    <div>
                      <div className="text-white font-semibold">UNWIND Governance Wire</div>
                      <div className="text-slate-500 text-[10px]">Bridge adapter pending</div>
                    </div>
                    <Badge variant="warning">UNCONFIGURED</Badge>
                  </div>
                </div>
              </Card>
            </div>
          </div>
        </div>
      )}

      {/* ----------------- TAB 2: WORKFLOW RUNS ----------------- */}
      {activeTab === "workflows" && (
        <Card className="space-y-4">
          <CardHeader
            title="Durable State Machine Workflows"
            subtitle="Checkpoint-backed executions with correlation tracking"
            action={
              <Button variant="primary" size="sm" onClick={() => setIsStartModalOpen(true)}>
                Start Workflow
              </Button>
            }
          />

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-900 text-slate-400 uppercase text-[10px] border-b border-slate-800">
                <tr>
                  <th className="p-3">Run ID</th>
                  <th className="p-3">Type</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Step</th>
                  <th className="p-3">Correlation ID</th>
                  <th className="p-3">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {workflows.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="p-6 text-center text-slate-500">
                      No workflow runs recorded yet.
                    </td>
                  </tr>
                ) : (
                  workflows.map((w) => (
                    <tr key={w.id} className="hover:bg-slate-900/40">
                      <td className="p-3 text-white font-bold cursor-pointer hover:text-cyan-300" onClick={() => inspectRun(w)}>
                        {w.id}
                      </td>
                      <td className="p-3 text-slate-300">{w.workflowType || (w as any).workflow_type}</td>
                      <td className="p-3">
                        <Badge
                          variant={
                            w.status === "COMPLETED" || (w.status as any) === "completed"
                              ? "success"
                              : (w.status as any) === "waiting_approval" || w.status === "PAUSED_APPROVAL"
                              ? "warning"
                              : w.status === "FAILED" || (w.status as any) === "failed"
                              ? "critical"
                              : "info"
                          }
                        >
                          {w.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-cyan-400">{w.currentStep || (w as any).step}</td>
                      <td className="p-3 text-slate-400">{w.correlationId || (w as any).correlation_id}</td>
                      <td className="p-3 flex items-center gap-2">
                        <Button variant="secondary" size="sm" onClick={() => inspectRun(w)}>
                          Detail
                        </Button>
                        {(w.status as any) === "running" || (w.status as any) === "waiting_approval" ? (
                          <Button variant="danger" size="sm" onClick={() => setConfirmCancelRunId(w.id)}>
                            Cancel
                          </Button>
                        ) : null}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ----------------- TAB 3: APPROVAL INBOX ----------------- */}
      {activeTab === "approvals" && (
        <Card className="space-y-4">
          <CardHeader
            title="Authoritative Governance Approval Inbox"
            subtitle="Consequential workflows paused at the UNWIND authority gate"
          />

          <div className="space-y-3">
            {approvals.length === 0 ? (
              <div className="p-8 text-center text-xs text-slate-500 font-mono">
                No approval requests currently waiting. All actions covered by active warrant lease.
              </div>
            ) : (
              approvals.map((a: any) => (
                <div
                  key={a.id}
                  className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4"
                >
                  <div className="space-y-1.5 max-w-2xl">
                    <div className="flex items-center gap-2">
                      <Badge variant={a.status === "granted" || a.state === "APPROVED" ? "success" : "warning"}>
                        {a.status || a.state}
                      </Badge>
                      <span className="font-mono text-xs text-white font-bold">{a.id}</span>
                      <span className="text-xs text-slate-500">•</span>
                      <span className="font-mono text-xs text-cyan-400 bg-cyan-950 px-2 py-0.5 rounded border border-cyan-800">
                        {a.scope}
                      </span>
                      <Badge variant="demo" size="sm">
                        DEV / TEST DECISION
                      </Badge>
                    </div>

                    <p className="text-sm font-semibold text-slate-200">
                      Workflow Run: <code className="text-cyan-300">{a.run_id || a.runId}</code> | Action: <code className="text-amber-300">{a.action}</code>
                    </p>

                    <div className="flex flex-wrap items-center gap-4 text-xs font-mono text-slate-400">
                      <span>Risk: {a.risk_level || a.severity}</span>
                      <span>Action Hash: {((a.action_hash || "") as string).substring(0, 16)}...</span>
                      <span>Expires: {new Date(a.expires_at || a.expiresAt).toLocaleTimeString()}</span>
                    </div>

                    <div className="p-2.5 rounded bg-amber-950/20 border border-amber-900/40 text-[11px] text-amber-300">
                      <strong>Governance Notice:</strong> Real UNWIND wire adapter is UNCONFIGURED. Local decisions submitted here are marked strictly as <em>DEVELOPMENT / TEST ONLY</em>.
                    </div>
                  </div>

                  {(a.status === "waiting_approval" || a.state === "PENDING") && (
                    <div className="flex items-center gap-2 shrink-0">
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => {
                          setDecisionModalApproval(a);
                          setDecisionChoice("granted");
                        }}
                      >
                        Grant (Test)
                      </Button>
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setDecisionModalApproval(a);
                          setDecisionChoice("rejected");
                        }}
                      >
                        Reject
                      </Button>
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </Card>
      )}

      {/* ----------------- TAB 4: NOTIFICATIONS ----------------- */}
      {activeTab === "notifications" && (
        <Card className="space-y-4">
          <CardHeader
            title="Multi-Channel Notification Outbox"
            subtitle="Local sink, delivery status receipts, and PII masking"
          />

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-900 text-slate-400 uppercase text-[10px] border-b border-slate-800">
                <tr>
                  <th className="p-3">ID</th>
                  <th className="p-3">Channel</th>
                  <th className="p-3">Destination (Masked)</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Provider</th>
                  <th className="p-3">Attempts</th>
                  <th className="p-3">Verified Receipt</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {notifications.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-slate-500">
                      No notifications recorded in local outbox yet.
                    </td>
                  </tr>
                ) : (
                  notifications.map((n: any) => (
                    <tr key={n.id} className="hover:bg-slate-900/40">
                      <td className="p-3 text-cyan-300 font-bold">{n.id}</td>
                      <td className="p-3 text-slate-300">{n.channel}</td>
                      <td className="p-3 text-white font-semibold">{n.destination_masked || n.destinationMasked}</td>
                      <td className="p-3">
                        <Badge
                          variant={
                            n.status === "DELIVERED"
                              ? "success"
                              : n.status === "ACCEPTED"
                              ? "info"
                              : n.status === "DEAD_LETTERED"
                              ? "critical"
                              : "neutral"
                          }
                        >
                          {n.status}
                        </Badge>
                      </td>
                      <td className="p-3 text-slate-400">{n.provider}</td>
                      <td className="p-3 text-slate-300">{n.attempts}</td>
                      <td className="p-3">
                        {n.delivery_verified || n.deliveryVerified ? (
                          <span className="text-emerald-400 font-bold">YES</span>
                        ) : (
                          <span className="text-slate-500">NO (UNVERIFIED)</span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ----------------- TAB 5: QUEUES & DEAD LETTERS ----------------- */}
      {activeTab === "queues" && (
        <div className="space-y-6">
          <Card>
            <CardHeader
              title="Dead-Letter Queue (DLQ)"
              subtitle="Failed jobs with exhausted retry budgets awaiting manual redrive"
            />
            <div className="space-y-3">
              {dlqItems.length === 0 ? (
                <div className="p-8 text-center text-xs text-slate-500 font-mono">
                  Dead-Letter Queue is empty. All messages processed successfully.
                </div>
              ) : (
                dlqItems.map((d: any) => (
                  <div
                    key={d.id}
                    className="p-4 rounded-xl bg-slate-900/60 border border-red-950/80 flex items-center justify-between gap-4"
                  >
                    <div className="space-y-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="critical">DEAD_LETTERED</Badge>
                        <span className="font-mono text-xs text-white font-bold">{d.id}</span>
                        <span className="text-xs text-slate-500">•</span>
                        <span className="text-xs text-slate-400">{d.kind}</span>
                      </div>
                      <p className="text-xs text-red-300 font-mono">Error: {d.error}</p>
                      <div className="text-[11px] font-mono text-slate-500">
                        Entity: {d.entity_id} | Redrives: {d.redrive_count} | Enqueued: {new Date(d.created_at).toLocaleString()}
                      </div>
                    </div>
                    <Button variant="danger" size="sm" onClick={() => setConfirmRedriveId(d.id)}>
                      Redrive Item
                    </Button>
                  </div>
                ))
              )}
            </div>
          </Card>
        </div>
      )}

      {/* ----------------- TAB 6: RELIABILITY & ALERTS ----------------- */}
      {activeTab === "reliability" && (
        <Card className="space-y-4">
          <CardHeader
            title="Reliability Monitoring & Heartbeat Alarms"
            subtitle="Automated fault detection, stuck workflows, and DLQ spike triggers"
          />

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {alarms.length === 0 ? (
              <div className="col-span-3 p-8 text-center text-xs text-slate-500 font-mono">
                No active alarms triggered. System reliability healthy.
              </div>
            ) : (
              alarms.map((al: any) => (
                <div key={al.alarm_name} className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-white">{al.alarm_name}</span>
                    <Badge variant={al.state === "ALARM" ? "critical" : "success"}>{al.state}</Badge>
                  </div>
                  <div className="text-xs text-slate-400">
                    Threshold: <span className="text-white font-mono">{al.threshold}</span>
                  </div>
                  <div className="text-[11px] text-slate-500">
                    {al.explanation || "No trigger explanation recorded"}
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      )}

      {/* ----------------- TAB 7: EVENT LOG ----------------- */}
      {activeTab === "events" && (
        <Card className="space-y-4">
          <CardHeader
            title="Append-Only Operations Audit Trail"
            subtitle="Enforced by database triggers; tamper-evident timeline"
          />

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-mono">
              <thead className="bg-slate-900 text-slate-400 uppercase text-[10px] border-b border-slate-800">
                <tr>
                  <th className="p-3">Time</th>
                  <th className="p-3">Type</th>
                  <th className="p-3">Entity</th>
                  <th className="p-3">Actor</th>
                  <th className="p-3">Details</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/80">
                {events.length === 0 ? (
                  <tr>
                    <td colSpan={5} className="p-6 text-center text-slate-500">
                      No events recorded.
                    </td>
                  </tr>
                ) : (
                  events.slice(0, 25).map((e: any) => (
                    <tr key={e.id} className="hover:bg-slate-900/40">
                      <td className="p-3 text-slate-400">{new Date(e.ts).toLocaleTimeString()}</td>
                      <td className="p-3 text-cyan-300 font-semibold">{e.type}</td>
                      <td className="p-3 text-slate-300">{e.entity_type}:{e.entity_id}</td>
                      <td className="p-3 text-slate-400">{e.actor}</td>
                      <td className="p-3 text-slate-400 max-w-xs truncate">
                        {JSON.stringify(e.detail || {})}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* ----------------- TAB 8: INTEGRATIONS ----------------- */}
      {activeTab === "integrations" && (
        <Card className="space-y-4">
          <CardHeader
            title="Autonomous Operations Provider Registry"
            subtitle="Verified setup status and safe integration guidance"
          />

          <div className="space-y-3">
            {[
              {
                name: "Local SQLite Store & In-Memory Queue",
                status: "LOCAL",
                variant: "connected",
                desc: "Durable SQLite database with append-only events table trigger.",
                envVars: ["AEGIS_DB_PATH"],
              },
              {
                name: "UNWIND Governance Wire Adapter",
                status: "UNCONFIGURED",
                variant: "warning",
                desc: "Live RPC wire contract to UNWIND Cloud Run service is unexercised. Local test approvals enabled.",
                envVars: ["AEGIS_UNWIND_URL", "AEGIS_UNWIND_KEY_ID"],
                blocker: "Awaiting live UNWIND wire contract alignment.",
              },
              {
                name: "Amazon SNS & SQS Adapters",
                status: "UNCONFIGURED",
                variant: "planned",
                desc: "AWS Step Functions state machines and SQS DLQ. Tested via fake providers only.",
                envVars: ["AWS_REGION", "AEGIS_SNS_EMAIL_TOPIC_ARN", "AEGIS_SQS_QUEUE_URL"],
                blocker: "No cloud resources deployed in local development.",
              },
              {
                name: "Meta WhatsApp Business Platform",
                status: "UNCONFIGURED",
                variant: "planned",
                desc: "WhatsApp Cloud API integration. Requires verified Meta business account token.",
                envVars: ["AEGIS_WA_PHONE_NUMBER_ID", "AEGIS_WA_ACCESS_TOKEN", "AEGIS_WA_WEBHOOK_VERIFY_TOKEN"],
                blocker: "Live credentials not configured.",
              },
            ].map((p) => (
              <div key={p.name} className="p-4 rounded-xl bg-slate-900 border border-slate-800 space-y-2">
                <div className="flex items-center justify-between">
                  <h4 className="font-semibold text-sm text-white">{p.name}</h4>
                  <Badge variant={p.variant as any}>{p.status}</Badge>
                </div>
                <p className="text-xs text-slate-400">{p.desc}</p>
                {p.blocker && (
                  <p className="text-xs text-amber-400 font-mono">Blocker: {p.blocker}</p>
                )}
                <div className="pt-2 border-t border-slate-800 text-[11px] font-mono text-slate-500">
                  Required Env Vars: {p.envVars.join(", ")}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Modal: Start Workflow */}
      <Modal
        isOpen={isStartModalOpen}
        onClose={() => setIsStartModalOpen(false)}
        title="Start Autonomous Operations Workflow"
        subtitle="Initiate a durable state machine run in local mode"
        footer={
          <>
            <Button variant="ghost" onClick={() => setIsStartModalOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={handleStartWorkflow}>
              Start Execution
            </Button>
          </>
        }
      >
        <div className="space-y-4 text-xs font-mono">
          <div>
            <label className="text-slate-300 block mb-1">Workflow Type:</label>
            <select
              value={startWorkflowType}
              onChange={(e) => setStartWorkflowType(e.target.value)}
              className="w-full p-2 rounded bg-slate-900 border border-slate-800 text-white"
            >
              <option value="sample.governed_action">sample.governed_action (Requires Approval)</option>
              <option value="sample.autonomous_sync">sample.autonomous_sync (Direct Run)</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="approvalReq"
              checked={startRequiresApproval}
              onChange={(e) => setStartRequiresApproval(e.target.checked)}
              className="rounded bg-slate-900 border-slate-700"
            />
            <label htmlFor="approvalReq" className="text-slate-200">
              Require Human Governance Approval Gate
            </label>
          </div>
        </div>
      </Modal>

      {/* Modal: Workflow Detail & Timeline */}
      {selectedRun && (
        <Modal
          isOpen={!!selectedRun}
          onClose={() => setSelectedRun(null)}
          title={`Workflow Run: ${selectedRun.id}`}
          subtitle={`Type: ${selectedRun.workflowType || (selectedRun as any).workflow_type}`}
          maxWidth="xl"
        >
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-2 gap-3 p-3 rounded-lg bg-slate-900 font-mono text-slate-300">
              <div>Status: <Badge variant="info">{selectedRun.status}</Badge></div>
              <div>Step: <span className="text-cyan-400">{selectedRun.currentStep || (selectedRun as any).step}</span></div>
              <div>Correlation: {selectedRun.correlationId || (selectedRun as any).correlation_id}</div>
              <div>Attempts: {selectedRun.attempts || 1}</div>
            </div>

            <div className="space-y-2">
              <h4 className="font-semibold text-white uppercase text-[10px] font-mono">Event Timeline</h4>
              <div className="space-y-2 max-h-60 overflow-y-auto">
                {selectedTimeline.length === 0 ? (
                  <div className="p-4 text-center text-slate-500 font-mono">No timeline events fetched.</div>
                ) : (
                  selectedTimeline.map((t: any) => (
                    <div key={t.id} className="p-2.5 rounded bg-slate-900 border border-slate-800 font-mono text-[11px]">
                      <div className="flex justify-between text-cyan-300">
                        <span>{t.type}</span>
                        <span className="text-slate-500">{new Date(t.ts).toLocaleTimeString()}</span>
                      </div>
                      <div className="text-slate-400">Actor: {t.actor}</div>
                      {t.detail && Object.keys(t.detail).length > 0 && (
                        <div className="text-slate-500 text-[10px] truncate">{JSON.stringify(t.detail)}</div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        </Modal>
      )}

      {/* Modal: Dev Decision */}
      {decisionModalApproval && (
        <ConfirmationModal
          isOpen={!!decisionModalApproval}
          onClose={() => setDecisionModalApproval(null)}
          onConfirm={handleSubmitDevDecision}
          title={`Submit Local Test Decision: ${decisionChoice.toUpperCase()}`}
          message={`Submit local test decision '${decisionChoice}' for approval request ${decisionModalApproval.id}. This action will resume the paused workflow execution.`}
          confirmLabel={`Submit ${decisionChoice.toUpperCase()}`}
          confirmVariant={decisionChoice === "granted" ? "primary" : "danger"}
          riskBadge="LOCAL TEST ONLY — NOT PRODUCTION AUTHORIZATION"
        />
      )}

      {/* Modal: Confirm Cancel */}
      {confirmCancelRunId && (
        <ConfirmationModal
          isOpen={!!confirmCancelRunId}
          onClose={() => setConfirmCancelRunId(null)}
          onConfirm={handleCancelRun}
          title="Confirm Workflow Cancellation"
          message={`Are you sure you want to cancel workflow ${confirmCancelRunId}? This will halt execution and append a cancellation audit event.`}
          confirmLabel="Cancel Workflow"
          confirmVariant="danger"
          riskBadge="IRREVERSIBLE CANCEL"
        />
      )}

      {/* Modal: Confirm Redrive */}
      {confirmRedriveId && (
        <ConfirmationModal
          isOpen={!!confirmRedriveId}
          onClose={() => setConfirmRedriveId(null)}
          onConfirm={handleRedrive}
          title="Confirm Dead-Letter Redrive"
          message={`Are you sure you want to redrive dead-letter message ${confirmRedriveId}? This will re-enqueue the message with an incremented redrive count.`}
          confirmLabel="Redrive Message"
          confirmVariant="primary"
          riskBadge="CONTROLLED REDRIVE"
        />
      )}
    </div>
  );
}
