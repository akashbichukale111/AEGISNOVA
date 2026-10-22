"use client";

import React, { useState } from "react";
import { GitBranch, Activity, Shield, AlertTriangle, Layers, ArrowRight } from "lucide-react";
import { Card, CardHeader } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";

export default function ImpactPage() {
  const [selectedService, setSelectedService] = useState<string>("telemetry-worker");

  const services = [
    {
      id: "telemetry-worker",
      name: "Telemetry & Ingestion Worker",
      repo: "devguard-ai",
      blastRadiusScore: 78,
      dependentsCount: 14,
      status: "AT_RISK",
      description: "Directly affected by CWE-89 injection in telemetry collector query.",
    },
    {
      id: "audit-chain-service",
      name: "Audit Chain & Ledger",
      repo: "devguard-enterprise",
      blastRadiusScore: 42,
      dependentsCount: 8,
      status: "SECURE",
      description: "Appends deterministic hash-linked records; isolated from raw telemetry queries.",
    },
    {
      id: "unwind-warrant-gateway",
      name: "UNWIND Warrant Authority Gateway",
      repo: "unwind-live-verified",
      blastRadiusScore: 12,
      dependentsCount: 22,
      status: "SECURE",
      description: "Pure integer zero-model authority fold. Survives external provider outages.",
    },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <div className="flex items-center gap-2">
          <h1 className="text-2xl font-bold text-white tracking-tight">Repository & Impact Analysis</h1>
          <Badge variant="demo">DEMO / GRAPH ADAPTER</Badge>
        </div>
        <p className="text-xs text-slate-400 mt-1">
          Downstream blast radius inspection and cross-repository dependency topology
        </p>
      </div>

      {/* Main Impact Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Monitored Services List (5 cols) */}
        <div className="lg:col-span-5 space-y-4">
          <Card>
            <CardHeader
              title="Monitored Services & Nodes"
              subtitle="Select a node to inspect dependency edges"
            />
            <div className="space-y-3">
              {services.map((svc) => {
                const isSelected = selectedService === svc.id;
                return (
                  <div
                    key={svc.id}
                    onClick={() => setSelectedService(svc.id)}
                    className={`p-4 rounded-xl border cursor-pointer transition-all ${
                      isSelected
                        ? "bg-cyan-950/40 border-cyan-500 shadow-[0_0_12px_rgba(6,182,212,0.15)]"
                        : "bg-slate-900/60 border-slate-800 hover:border-slate-700"
                    }`}
                  >
                    <div className="flex items-center justify-between mb-1.5">
                      <h4 className="text-sm font-semibold text-white">{svc.name}</h4>
                      <Badge variant={svc.status === "AT_RISK" ? "critical" : "success"} size="sm">
                        {svc.status}
                      </Badge>
                    </div>
                    <p className="text-xs text-slate-400 mb-2">{svc.description}</p>
                    <div className="flex items-center justify-between text-[11px] font-mono text-slate-400 pt-2 border-t border-slate-800/80">
                      <span>Repo: {svc.repo}</span>
                      <span>Blast Radius: <strong className="text-cyan-400">{svc.blastRadiusScore}%</strong></span>
                    </div>
                  </div>
                );
              })}
            </div>
          </Card>
        </div>

        {/* Right Column: Visual Graph Surface & Blast Radius (7 cols) */}
        <div className="lg:col-span-7 space-y-4">
          <Card>
            <CardHeader
              title="Blast Radius & Graph Topology"
              subtitle="Deterministic reverse index cascade traversal"
              badge={<Badge variant="info">T0 ARITHMETIC</Badge>}
            />

            <div className="p-6 rounded-xl bg-black/60 border border-slate-800 space-y-6">
              {/* Visual simulated graph nodes */}
              <div className="flex items-center justify-between gap-4 p-4 rounded-lg bg-slate-900/80 border border-slate-800 text-xs">
                <div className="p-3 rounded-lg bg-red-950/60 border border-red-800 text-red-300 font-mono text-center">
                  <div className="font-bold">telemetry.py</div>
                  <div className="text-[10px] text-red-400">Vulnerability Root</div>
                </div>
                <ArrowRight className="h-5 w-5 text-slate-600 animate-pulse" />
                <div className="p-3 rounded-lg bg-amber-950/60 border border-amber-800 text-amber-300 font-mono text-center">
                  <div className="font-bold">traces_db_writer</div>
                  <div className="text-[10px] text-amber-400">Direct Dependent</div>
                </div>
                <ArrowRight className="h-5 w-5 text-slate-600 animate-pulse" />
                <div className="p-3 rounded-lg bg-cyan-950/60 border border-cyan-800 text-cyan-300 font-mono text-center">
                  <div className="font-bold">signoz_collector</div>
                  <div className="text-[10px] text-cyan-400">Downstream Consumer</div>
                </div>
              </div>

              <div className="space-y-3">
                <h4 className="text-xs font-mono uppercase text-slate-400 font-semibold">
                  Downstream Blast Radius Metrics
                </h4>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                  <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                    <div className="text-[10px] text-slate-400">Direct Dependents</div>
                    <div className="text-lg font-bold font-mono text-white mt-0.5">14 Services</div>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                    <div className="text-[10px] text-slate-400">Estimated Shock</div>
                    <div className="text-lg font-bold font-mono text-amber-400 mt-0.5">High (Tier 1)</div>
                  </div>
                  <div className="p-3 rounded-lg bg-slate-900 border border-slate-800">
                    <div className="text-[10px] text-slate-400">Model Calls Needed</div>
                    <div className="text-lg font-bold font-mono text-emerald-400 mt-0.5">0 Calls</div>
                  </div>
                </div>
              </div>

              <div className="p-3.5 rounded-lg bg-cyan-950/20 border border-cyan-800/40 text-xs text-cyan-300">
                <strong>UNWIND Architecture Note:</strong> Blast-radius traversal is a graph traversal (thousands of nodes, no model). Materiality is an arithmetic filter (`shock &gt; slack`). Asking a model to do graph subtraction results in hallucinated impacts.
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
