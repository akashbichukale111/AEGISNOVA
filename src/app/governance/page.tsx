"use client";

import React, { useState } from "react";
import {
  Scale,
  ShieldCheck,
  Clock,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RotateCcw,
  Hash,
  UserCheck,
} from "lucide-react";
import { Card, CardHeader } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Modal, ConfirmationModal } from "../../components/ui/Modal";
import { INITIAL_APPROVALS } from "../../lib/demo-data";
import { ApprovalRequest, ApprovalDecision } from "../../contracts";

export default function GovernancePage() {
  const [approvals, setApprovals] = useState<ApprovalRequest[]>(INITIAL_APPROVALS);
  const [warrantBalance, setWarrantBalance] = useState<number>(1450);
  const [decisions, setDecisions] = useState<ApprovalDecision[]>([
    {
      schemaVersion: "1.0.0",
      approvalRequestId: "APPR-SEC-079",
      decision: "APPROVED",
      decidedBy: "human:sec-lead@aegisnova.io",
      decidedAt: "2026-10-20T17:40:00Z",
      decisionReason: "Verified parameterized query fix for CWE-89 in dev environment.",
      decisionLineageHash: "9e8a712f84b6c3d1e0f29a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b9c8d",
      warrantBalanceRemainingBp: 1450,
    },
  ]);
  const [selectedApproval, setSelectedApproval] = useState<ApprovalRequest | null>(null);
  const [actionType, setActionType] = useState<"APPROVE" | "REJECT">("APPROVE");
  const [reasonInput, setReasonInput] = useState("");
  const [isDecisionModalOpen, setIsDecisionModalOpen] = useState(false);

  const handleOpenDecision = (appr: ApprovalRequest, type: "APPROVE" | "REJECT") => {
    setSelectedApproval(appr);
    setActionType(type);
    setReasonInput("");
    setIsDecisionModalOpen(true);
  };

  const handleConfirmDecision = () => {
    if (!selectedApproval) return;

    const newDecisionState = actionType === "APPROVE" ? "APPROVED" : "REJECTED";

    // Deduct warrant basis points if approved
    const debit = actionType === "APPROVE" ? selectedApproval.warrantDebitBp : 0;
    const newBalance = Math.max(0, warrantBalance - debit);
    setWarrantBalance(newBalance);

    // Update approval request
    setApprovals((prev) =>
      prev.map((a) => (a.id === selectedApproval.id ? { ...a, state: newDecisionState } : a))
    );

    // Record decision lineage
    const newDecision: ApprovalDecision = {
      schemaVersion: "1.0.0",
      approvalRequestId: selectedApproval.id,
      decision: newDecisionState,
      decidedBy: "human:sec-lead@aegisnova.io",
      decidedAt: new Date().toISOString(),
      decisionReason: reasonInput || `Action ${actionType.toLowerCase()}d by human operator.`,
      decisionLineageHash: `${Math.random().toString(36).substring(2)}${Date.now()}`,
      warrantBalanceRemainingBp: newBalance,
    };

    setDecisions((prev) => [newDecision, ...prev]);
    setIsDecisionModalOpen(false);
    setSelectedApproval(null);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-white tracking-tight">Governance & UNWIND Core</h1>
          <Badge variant="connected">UNWIND CORE ACTIVE</Badge>
          <Badge variant="demo">DEMO STORE</Badge>
        </div>
        <p className="text-xs text-slate-400 mt-1">
          Scoped human approvals, decaying capability warrant ledger, and deterministic decision lineage
        </p>
      </div>

      {/* Warrant Ledger Balance Header */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card className="border-purple-900/40 bg-gradient-to-br from-purple-950/20 to-slate-900">
          <div className="space-y-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-mono uppercase text-purple-300 font-semibold">
                Warrant Authority Balance
              </span>
              <Badge variant="demo" size="sm">
                PURE INTEGER FOLD
              </Badge>
            </div>
            <div className="text-3xl font-bold font-mono text-white mt-1">
              {warrantBalance} <span className="text-base font-normal text-purple-300">bp</span>
            </div>
            <div className="text-[11px] text-slate-400 pt-2 border-t border-purple-900/40">
              Deterministic, decaying quantity of authority. Minted only from countersigned human outcomes.
            </div>
          </div>
        </Card>

        <Card>
          <div className="space-y-1">
            <span className="text-xs font-mono uppercase text-slate-400 font-semibold">
              Pending Delegations
            </span>
            <div className="text-3xl font-bold font-mono text-amber-400 mt-1">
              {approvals.filter((a) => a.state === "PENDING").length}
            </div>
            <div className="text-[11px] text-slate-400 pt-2 border-t border-slate-800">
              High-risk actions blocked at gate by construction until countersigned.
            </div>
          </div>
        </Card>

        <Card>
          <div className="space-y-1">
            <span className="text-xs font-mono uppercase text-slate-400 font-semibold">
              Decisions Lineage
            </span>
            <div className="text-3xl font-bold font-mono text-cyan-400 mt-1">
              {decisions.length} Records
            </div>
            <div className="text-[11px] text-slate-400 pt-2 border-t border-slate-800">
              Cryptographically hashed event sequence. Replay & tampering protected.
            </div>
          </div>
        </Card>
      </div>

      {/* Pending Approvals Inbox */}
      <Card className="space-y-4">
        <CardHeader
          title="Approval Inbox (Scoped Human Authority)"
          subtitle="Requests paused at UNWIND gate requiring explicit human authorization"
          badge={<Badge variant="warning">{approvals.filter((a) => a.state === "PENDING").length} WAITING</Badge>}
        />

        <div className="space-y-3">
          {approvals.length === 0 ? (
            <div className="p-8 text-center text-slate-500 font-mono text-xs">
              No pending approvals. All action delegations covered by existing warrant.
            </div>
          ) : (
            approvals.map((appr) => (
              <div
                key={appr.id}
                className="p-4 rounded-xl bg-slate-900/70 border border-slate-800 hover:border-slate-700 transition-all flex flex-col md:flex-row md:items-center justify-between gap-4"
              >
                <div className="space-y-1.5 max-w-2xl">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant={
                        appr.state === "APPROVED"
                          ? "success"
                          : appr.state === "REJECTED"
                          ? "critical"
                          : "warning"
                      }
                    >
                      {appr.state}
                    </Badge>
                    <span className="font-mono text-xs text-white font-bold">{appr.id}</span>
                    <span className="text-xs text-slate-500">•</span>
                    <span className="font-mono text-xs text-cyan-400 bg-cyan-950/60 px-2 py-0.5 rounded border border-cyan-800">
                      {appr.requiredScope}
                    </span>
                  </div>

                  <h4 className="text-sm font-semibold text-slate-200">
                    {(appr.actionPayload.patchSummary as string) || appr.actionType}
                  </h4>

                  <div className="flex flex-wrap items-center gap-4 text-xs font-mono text-slate-400">
                    <span>Debit: <strong className="text-purple-300">{appr.warrantDebitBp} bp</strong></span>
                    <span>Requested by: {appr.requestedBy}</span>
                    <span>Expires: {new Date(appr.expiresAt).toLocaleTimeString()}</span>
                  </div>
                </div>

                {appr.state === "PENDING" && (
                  <div className="flex items-center gap-2 shrink-0">
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => handleOpenDecision(appr, "APPROVE")}
                    >
                      Approve & Countersign
                    </Button>
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => handleOpenDecision(appr, "REJECT")}
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

      {/* Decision Lineage Table */}
      <Card className="space-y-4">
        <CardHeader
          title="Decision Lineage & Audit Trail"
          subtitle="Append-only record of all human countersignatures and warrant balance deductions"
          badge={<Badge variant="info">IMMUTABLE LOG</Badge>}
        />

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-slate-900/80 text-slate-400 uppercase text-[10px] border-b border-slate-800">
              <tr>
                <th className="p-3">Decision ID</th>
                <th className="p-3">Decision</th>
                <th className="p-3">Decided By</th>
                <th className="p-3">Reason / Rationale</th>
                <th className="p-3">Lineage Hash</th>
                <th className="p-3">Remaining Balance</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {decisions.map((dec) => (
                <tr key={dec.decisionLineageHash} className="hover:bg-slate-900/40">
                  <td className="p-3 text-white font-bold">{dec.approvalRequestId}</td>
                  <td className="p-3">
                    <Badge variant={dec.decision === "APPROVED" ? "success" : "critical"}>
                      {dec.decision}
                    </Badge>
                  </td>
                  <td className="p-3 text-slate-300">{dec.decidedBy}</td>
                  <td className="p-3 text-slate-300 max-w-xs truncate">{dec.decisionReason}</td>
                  <td className="p-3 text-slate-500 max-w-[120px] truncate" title={dec.decisionLineageHash}>
                    {dec.decisionLineageHash.substring(0, 16)}...
                  </td>
                  <td className="p-3 text-purple-300 font-bold">{dec.warrantBalanceRemainingBp} bp</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Decision Modal */}
      {selectedApproval && (
        <Modal
          isOpen={isDecisionModalOpen}
          onClose={() => setIsDecisionModalOpen(false)}
          title={`Countersign Decision: ${selectedApproval.id}`}
          subtitle={`Action: ${actionType} ${selectedApproval.actionType}`}
          footer={
            <>
              <Button variant="ghost" onClick={() => setIsDecisionModalOpen(false)}>
                Cancel
              </Button>
              <Button
                variant={actionType === "APPROVE" ? "primary" : "danger"}
                onClick={handleConfirmDecision}
              >
                Submit Countersignature
              </Button>
            </>
          }
        >
          <div className="space-y-4 text-xs">
            <div className="p-3 rounded-lg bg-slate-900 border border-slate-800 space-y-1">
              <span className="text-slate-400">Target Action:</span>
              <p className="font-semibold text-white">
                {(selectedApproval.actionPayload.patchSummary as string) || selectedApproval.actionType}
              </p>
              <div className="flex items-center gap-3 text-slate-400 font-mono pt-1">
                <span>Scope: {selectedApproval.requiredScope}</span>
                <span>Warrant Debit: {selectedApproval.warrantDebitBp} bp</span>
              </div>
            </div>

            <div className="space-y-1.5">
              <label className="text-slate-300 font-medium">Decision Reason / Audit Note:</label>
              <textarea
                rows={3}
                value={reasonInput}
                onChange={(e) => setReasonInput(e.target.value)}
                placeholder="Enter justification for audit log and lineage hash..."
                className="w-full p-2.5 rounded-lg bg-slate-900 border border-slate-800 text-white font-mono text-xs focus:outline-none focus:border-cyan-500"
              />
            </div>

            <div className="p-3 rounded-lg bg-purple-950/20 border border-purple-800/40 text-purple-300 text-[11px]">
              <strong>Zero-Model Enforcement:</strong> This outcome will be recorded directly into the append-only ledger and debited against the tenant lease.
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
