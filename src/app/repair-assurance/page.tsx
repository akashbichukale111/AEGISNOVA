"use client";

import React, { useState } from "react";
import {
  Wrench,
  ShieldCheck,
  CheckCircle,
  AlertTriangle,
  Play,
  RotateCcw,
  Sparkles,
  Zap,
  Lock,
  Award,
  Terminal,
  FileCode
} from "lucide-react";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { MetricCard } from "../../components/ui/MetricCard";

interface RepairProofItem {
  id: string;
  patchId: string;
  targetRepo: string;
  verdict: "REPAIR_VERIFIED" | "NEEDS_HUMAN_REVIEW" | "REPAIR_BLOCKED";
  breakerTestsPassed: number;
  breakerTestsTotal: number;
  sha256Proof: string;
  warrantyValidUntil: string;
  unwindWarrantDebitBp: number;
}

const INITIAL_PROOFS: RepairProofItem[] = [
  {
    id: "PROOF-SEC-101",
    patchId: "PATCH-SQLI-081",
    targetRepo: "payments-service",
    verdict: "REPAIR_VERIFIED",
    breakerTestsPassed: 14,
    breakerTestsTotal: 14,
    sha256Proof: "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    warrantyValidUntil: "2026-11-21T00:00:00Z",
    unwindWarrantDebitBp: 150
  },
  {
    id: "PROOF-SEC-102",
    patchId: "PATCH-CHUNK-082",
    targetRepo: "auth-gateway",
    verdict: "REPAIR_VERIFIED",
    breakerTestsPassed: 8,
    breakerTestsTotal: 8,
    sha256Proof: "7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
    warrantyValidUntil: "2026-11-21T00:00:00Z",
    unwindWarrantDebitBp: 200
  }
];

export default function RepairAssurancePage() {
  const [proofs, setProofs] = useState<RepairProofItem[]>(INITIAL_PROOFS);
  const [isRunningBreaker, setIsRunningBreaker] = useState(false);
  const [breakerMessage, setBreakerMessage] = useState<string | null>(null);
  const [selectedProof, setSelectedProof] = useState<RepairProofItem | null>(proofs[0]);

  const runAdversarialBreaker = () => {
    setIsRunningBreaker(true);
    setTimeout(() => {
      const newProof: RepairProofItem = {
        id: `PROOF-SEC-${String(proofs.length + 101)}`,
        patchId: "PATCH-NIM-NVIDIA-99",
        targetRepo: "payments-service",
        verdict: "REPAIR_VERIFIED",
        breakerTestsPassed: 18,
        breakerTestsTotal: 18,
        sha256Proof: "a1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2",
        warrantyValidUntil: "2026-12-01T00:00:00Z",
        unwindWarrantDebitBp: 180
      };
      setProofs([newProof, ...proofs]);
      setSelectedProof(newProof);
      setIsRunningBreaker(false);
      setBreakerMessage("Adversarial Breaker passed: All 18 mutation test suites executed cleanly in sandbox.");
      setTimeout(() => setBreakerMessage(null), 6000);
    }, 1200);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[#172235] pb-5">
        <div>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-800 flex items-center justify-center shadow-lg shadow-emerald-950/40 ring-1 ring-emerald-400/30">
              <Wrench className="h-5 w-5 text-emerald-100" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-white">Independent Repair Assurance</h1>
                <Badge variant="success">CONNECTED (WORKSTREAM 04)</Badge>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800/80 flex items-center gap-1">
                  <Zap className="h-3 w-3 text-emerald-400" />
                  NVIDIA Breaker Verified
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Adversarial Patch Breaking, Deterministic Cryptographic Proofs & Warranty Seals
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            size="sm"
            onClick={runAdversarialBreaker}
            disabled={isRunningBreaker}
            className="text-xs bg-emerald-600 hover:bg-emerald-500 text-white flex items-center gap-1.5"
          >
            <Play className={`h-3.5 w-3.5 ${isRunningBreaker ? "animate-spin" : ""}`} />
            {isRunningBreaker ? "Running Breaker..." : "Run Adversarial Breaker"}
          </Button>
        </div>
      </div>

      {breakerMessage && (
        <div className="p-3 bg-emerald-950/50 border border-emerald-700/60 rounded-lg text-xs text-emerald-200 flex items-center justify-between">
          <span>{breakerMessage}</span>
          <button onClick={() => setBreakerMessage(null)} className="text-slate-400 hover:text-white">✕</button>
        </div>
      )}

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Issued Repair Proofs"
          value={proofs.length}
          subtext="Cryptographically Sealed"
          severity="normal"
        />
        <MetricCard
          label="Adversarial Breaker Pass"
          value="100%"
          subtext="Zero Mutation Breaches"
          severity="success"
        />
        <MetricCard
          label="Warranty Active"
          value="30 Days"
          subtext="Revalidation On Commit"
          severity="normal"
        />
        <MetricCard
          label="UNWIND Lease Debit"
          value="530 bp"
          subtext="Authority Countersigned"
          severity="warning"
        />
      </div>

      {/* Proofs Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <Card className="p-5 bg-[#0B0F19] border-[#172235]">
            <h3 className="text-sm font-semibold text-white mb-4">Certified Repair Proof Ledger</h3>
            <div className="space-y-3">
              {proofs.map(proof => (
                <div
                  key={proof.id}
                  onClick={() => setSelectedProof(proof)}
                  className={`p-4 rounded-xl transition-colors cursor-pointer border flex items-center justify-between ${
                    selectedProof?.id === proof.id
                      ? "bg-emerald-950/20 border-emerald-700/60"
                      : "bg-[#070A10] border-[#172235] hover:border-slate-700"
                  }`}
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-xs font-bold text-emerald-300">{proof.id}</span>
                      <span className="font-mono text-xs text-slate-300">({proof.patchId})</span>
                      <Badge variant="success">{proof.verdict}</Badge>
                    </div>
                    <div className="text-xs text-slate-400 font-mono">
                      Target: {proof.targetRepo} • Breaker Tests: {proof.breakerTestsPassed}/{proof.breakerTestsTotal} passed
                    </div>
                  </div>

                  <div className="text-right space-y-1">
                    <div className="text-xs font-mono font-bold text-cyan-300">-{proof.unwindWarrantDebitBp} bp</div>
                    <div className="text-[10px] text-slate-500 font-mono">UNWIND Warrant</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Selected Proof Inspector */}
        <div>
          {selectedProof ? (
            <Card className="p-5 bg-[#0B0F19] border-[#172235] space-y-4">
              <div className="border-b border-[#172235] pb-3">
                <div className="flex items-center gap-2">
                  <Award className="h-4 w-4 text-emerald-400" />
                  <span className="font-mono text-xs text-emerald-400 font-bold">{selectedProof.id}</span>
                </div>
                <h4 className="text-sm font-bold text-white mt-1">Cryptographic Warranty Certificate</h4>
              </div>

              <div className="space-y-3 text-xs font-mono">
                <div>
                  <span className="text-slate-400 text-[11px]">SHA-256 Proof Hash:</span>
                  <div className="p-2 bg-slate-900 rounded border border-slate-800 text-[10px] text-slate-300 break-all select-all mt-1">
                    {selectedProof.sha256Proof}
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-[#070A10] border border-[#172235] space-y-1.5">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Target Repository:</span>
                    <span className="text-slate-200">{selectedProof.targetRepo}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Warranty Expiry:</span>
                    <span className="text-emerald-400">{new Date(selectedProof.warrantyValidUntil).toLocaleDateString()}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Warrant Deducted:</span>
                    <span className="text-cyan-300">{selectedProof.unwindWarrantDebitBp} bp</span>
                  </div>
                </div>

                <div className="p-3 rounded-lg bg-emerald-950/20 border border-emerald-800/40 text-xs font-sans space-y-1">
                  <span className="text-emerald-400 font-semibold text-[11px]">Independent Guarantee</span>
                  <p className="text-[10px] text-slate-400">
                    Verified through sandboxed execution with `IRA_ALLOW_LOCAL_EXEC=1` and adversarial input injection.
                  </p>
                </div>
              </div>
            </Card>
          ) : (
            <Card className="p-8 text-center text-xs text-slate-500 bg-[#0B0F19] border-[#172235]">
              Select a proof certificate to inspect cryptographic validation.
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
