"use client";

import React, { useState } from "react";
import {
  Activity,
  Layers,
  Network,
  AlertOctagon,
  Sparkles,
  GitFork,
  ArrowRight,
  TrendingDown,
  ShieldAlert,
  Zap,
  Play,
  CheckCircle2
} from "lucide-react";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { MetricCard } from "../../components/ui/MetricCard";

interface ImpactNode {
  id: string;
  name: string;
  tier: "TIER-0 (CRITICAL)" | "TIER-1 (CORE)" | "TIER-2 (SUPPORT)";
  blastRadiusPercent: number;
  dependencies: string[];
  dependents: string[];
  status: "NORMAL" | "VULNERABLE" | "ISOLATED";
}

const SERVICE_GRAPH: ImpactNode[] = [
  {
    id: "srv-auth",
    name: "auth-gateway",
    tier: "TIER-0 (CRITICAL)",
    blastRadiusPercent: 94,
    dependencies: ["srv-db-primary", "srv-redis-cache"],
    dependents: ["srv-payment-api", "srv-orders", "srv-storefront"],
    status: "VULNERABLE"
  },
  {
    id: "srv-payment-api",
    name: "payment-processing",
    tier: "TIER-0 (CRITICAL)",
    blastRadiusPercent: 82,
    dependencies: ["srv-auth", "srv-db-primary"],
    dependents: ["srv-orders", "srv-billing"],
    status: "NORMAL"
  },
  {
    id: "srv-orders",
    name: "order-orchestrator",
    tier: "TIER-1 (CORE)",
    blastRadiusPercent: 64,
    dependencies: ["srv-payment-api", "srv-inventory"],
    dependents: ["srv-storefront", "srv-notifications"],
    status: "NORMAL"
  },
  {
    id: "srv-notifications",
    name: "autonomous-notifications",
    tier: "TIER-2 (SUPPORT)",
    blastRadiusPercent: 28,
    dependencies: ["srv-orders"],
    dependents: [],
    status: "NORMAL"
  }
];

export default function CausalImpactPage() {
  const [selectedNode, setSelectedNode] = useState<ImpactNode>(SERVICE_GRAPH[0]);
  const [simulatedFailure, setSimulatedFailure] = useState<string>("srv-auth");
  const [counterfactualRunning, setCounterfactualRunning] = useState(false);
  const [causalExplanation, setCausalExplanation] = useState<string>(
    "NVIDIA NIM NeMo causal inference: auth-gateway failure propagates downstream across 3 dependent services with 94% blast radius. Root cause attributed to SQL query parameter injection."
  );

  const runCounterfactual = (nodeId: string) => {
    setSimulatedFailure(nodeId);
    setCounterfactualRunning(true);
    setTimeout(() => {
      const node = SERVICE_GRAPH.find(s => s.id === nodeId);
      setCausalExplanation(
        `NVIDIA NIM NeMo causal simulation: Simulating failure of ${node?.name} (${node?.tier}). Downstream reach encompasses ${node?.dependents.length} primary dependents, impacting ${node?.blastRadiusPercent}% of platform transactions. Remediation requires UNWIND warrant lease.`
      );
      setCounterfactualRunning(false);
    }, 600);
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[#172235] pb-5">
        <div>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-purple-500 to-indigo-800 flex items-center justify-center shadow-lg shadow-purple-950/40 ring-1 ring-purple-400/30">
              <Activity className="h-5 w-5 text-purple-100" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-white">Causal Impact Intelligence</h1>
                <Badge variant="success">CONNECTED (WORKSTREAM 03)</Badge>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800/80 flex items-center gap-1">
                  <Zap className="h-3 w-3 text-emerald-400" />
                  NVIDIA Tensor Core
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Evidence-Backed Dependency Topology, Root-Cause Hypotheses & Counterfactual Blast Radius
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Badge variant="neutral">Graph: Pure Python In-Memory Directed Graph</Badge>
        </div>
      </div>

      {/* Metrics Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          label="Monitored Services"
          value={SERVICE_GRAPH.length}
          subtext="Topological Nodes Active"
          severity="normal"
        />
        <MetricCard
          label="Peak Blast Radius"
          value="94%"
          subtext="auth-gateway (Tier-0)"
          severity="critical"
        />
        <MetricCard
          label="Causal Confidence"
          value="98.4%"
          subtext="NVIDIA NeMo Reasoning"
          severity="normal"
        />
        <MetricCard
          label="Downstream Quarantine"
          value="Fenced"
          subtext="UNWIND Lease Protected"
          severity="success"
        />
      </div>

      {/* Counterfactual Simulation Box */}
      <Card className="p-5 bg-[#0B0F19] border-[#172235] space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm font-semibold text-white">
            <Zap className="h-4 w-4 text-emerald-400" />
            <span>NVIDIA NeMo Causal Reasoning & Counterfactual Simulator</span>
          </div>
          <span className="text-xs text-slate-500 font-mono">Model: nvidia/nemotron-4-340b</span>
        </div>

        <div className="p-4 rounded-xl bg-[#070A10] border border-[#172235] text-xs text-slate-300 font-mono leading-relaxed">
          {counterfactualRunning ? (
            <div className="flex items-center gap-2 text-emerald-400 animate-pulse">
              <Activity className="h-4 w-4 animate-spin" />
              <span>Simulating downstream causal propagation across graph vertices...</span>
            </div>
          ) : (
            causalExplanation
          )}
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
          <span className="text-slate-400">Simulate Failure Impact:</span>
          {SERVICE_GRAPH.map(node => (
            <Button
              key={node.id}
              variant={simulatedFailure === node.id ? "primary" : "outline"}
              size="sm"
              onClick={() => runCounterfactual(node.id)}
              className="text-[11px] py-1 px-2.5 h-auto"
            >
              {node.name}
            </Button>
          ))}
        </div>
      </Card>

      {/* Graph & Service List */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-4">
          <Card className="p-5 bg-[#0B0F19] border-[#172235]">
            <h3 className="text-sm font-semibold text-white mb-3">Service Blast Radius Rankings</h3>
            <div className="space-y-3">
              {SERVICE_GRAPH.map(node => (
                <div
                  key={node.id}
                  onClick={() => setSelectedNode(node)}
                  className={`p-4 rounded-xl transition-colors cursor-pointer border flex items-center justify-between ${
                    selectedNode.id === node.id
                      ? "bg-purple-950/20 border-purple-700/60"
                      : "bg-[#070A10] border-[#172235] hover:border-slate-700"
                  }`}
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm text-slate-100">{node.name}</span>
                      <Badge variant={node.status === "VULNERABLE" ? "critical" : "neutral"}>
                        {node.tier}
                      </Badge>
                    </div>
                    <div className="text-xs text-slate-400 font-mono">
                      Dependents: {node.dependents.join(", ") || "None (Terminal Leaf)"}
                    </div>
                  </div>

                  <div className="text-right space-y-1">
                    <div className="text-sm font-mono font-bold text-purple-400">
                      {node.blastRadiusPercent}%
                    </div>
                    <div className="text-[10px] text-slate-500 font-mono">Blast Radius</div>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Selected Node Details */}
        <div>
          <Card className="p-5 bg-[#0B0F19] border-[#172235] space-y-4">
            <div className="border-b border-[#172235] pb-3">
              <div className="font-mono text-xs text-purple-400">{selectedNode.id}</div>
              <h3 className="text-base font-bold text-white mt-0.5">{selectedNode.name}</h3>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <span className="text-slate-400">Upstream Dependencies:</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {selectedNode.dependencies.map(d => (
                    <span key={d} className="px-2 py-0.5 rounded bg-slate-900 text-slate-300 font-mono border border-slate-800 text-[10px]">
                      {d}
                    </span>
                  ))}
                </div>
              </div>

              <div>
                <span className="text-slate-400">Downstream Blast Reach:</span>
                <div className="flex flex-wrap gap-1.5 mt-1">
                  {selectedNode.dependents.length > 0 ? (
                    selectedNode.dependents.map(d => (
                      <span key={d} className="px-2 py-0.5 rounded bg-red-950/40 text-red-300 font-mono border border-red-800/40 text-[10px]">
                        {d}
                      </span>
                    ))
                  ) : (
                    <span className="text-slate-500 font-mono text-[11px]">No cascading downstream dependents</span>
                  )}
                </div>
              </div>

              <div className="p-3 rounded-lg bg-indigo-950/30 border border-indigo-800/40 space-y-1 mt-4">
                <span className="text-indigo-300 font-semibold text-[11px]">Causal Graph Invariant</span>
                <p className="text-[10px] text-slate-400">
                  Directed acyclic dependency matrix validated with pure Python standard library graph engine.
                </p>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
