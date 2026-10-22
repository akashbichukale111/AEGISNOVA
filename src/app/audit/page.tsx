"use client";

import React, { useState } from "react";
import { ScrollText, Search, Filter, ShieldCheck, Activity, Terminal, Download } from "lucide-react";
import { Card, CardHeader } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { INITIAL_AUDIT_LOGS } from "../../lib/demo-data";
import { AuditEvent } from "../../contracts";

export default function AuditPage() {
  const [logs, setLogs] = useState<AuditEvent[]>(INITIAL_AUDIT_LOGS);
  const [searchQuery, setSearchQuery] = useState("");
  const [outcomeFilter, setOutcomeFilter] = useState("ALL");

  const filteredLogs = logs.filter((log) => {
    const matchesOutcome = outcomeFilter === "ALL" || log.outcome === outcomeFilter;
    const matchesSearch =
      log.action.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.actor.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.targetResource.toLowerCase().includes(searchQuery.toLowerCase()) ||
      log.correlationId.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesOutcome && matchesSearch;
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-white tracking-tight">Audit & Observability</h1>
            <Badge variant="demo">DEMO / CORRELATED TRACES</Badge>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            End-to-end trace correlation IDs, SRE circuit breaker status, and security audit chain
          </p>
        </div>

        <Button
          variant="outline"
          size="sm"
          icon={<Download className="h-4 w-4" />}
          onClick={() => {
            alert("Audit log exported in JSON Lines format.");
          }}
        >
          Export Audit Trail
        </Button>
      </div>

      {/* SRE Health & Breaker Strip */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card className="p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400">Circuit Breaker</span>
            <Badge variant="success" size="sm">CLOSED (NORMAL)</Badge>
          </div>
          <div className="text-lg font-bold font-mono text-white mt-1">0 Trips</div>
          <div className="text-[10px] text-slate-500 mt-1">DevGuard Resilience Layer</div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400">SLO Latency Budget</span>
            <Badge variant="info" size="sm">99.8%</Badge>
          </div>
          <div className="text-lg font-bold font-mono text-cyan-400 mt-1">&lt; 3.0s Budget</div>
          <div className="text-[10px] text-slate-500 mt-1">Window: 100 requests</div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400">Telemetry Ingestion</span>
            <Badge variant="connected" size="sm">ACTIVE</Badge>
          </div>
          <div className="text-lg font-bold font-mono text-emerald-400 mt-1">OpenTelemetry</div>
          <div className="text-[10px] text-slate-500 mt-1">Local Collector</div>
        </Card>

        <Card className="p-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-mono text-slate-400">Audit Verification</span>
            <Badge variant="success" size="sm">PASSING</Badge>
          </div>
          <div className="text-lg font-bold font-mono text-purple-400 mt-1">Hash Verified</div>
          <div className="text-[10px] text-slate-500 mt-1">Append-only chain valid</div>
        </Card>
      </div>

      {/* Audit Log Table */}
      <Card className="space-y-4">
        <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search by action, actor, resource or correlation ID..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-white focus:outline-none focus:border-cyan-500 font-mono"
            />
          </div>

          <div className="flex items-center gap-2">
            <Filter className="h-3.5 w-3.5 text-slate-400" />
            <select
              value={outcomeFilter}
              onChange={(e) => setOutcomeFilter(e.target.value)}
              aria-label="Filter audit logs by outcome"
              className="px-2.5 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 font-mono focus:outline-none"
            >
              <option value="ALL">All Outcomes</option>
              <option value="SUCCESS">Success</option>
              <option value="INTERCEPTED">Intercepted (Gate)</option>
              <option value="FAILURE">Failure</option>
            </select>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-mono">
            <thead className="bg-slate-900/80 text-slate-400 uppercase text-[10px] border-b border-slate-800">
              <tr>
                <th className="p-3">Log ID</th>
                <th className="p-3">Timestamp</th>
                <th className="p-3">Action</th>
                <th className="p-3">Actor</th>
                <th className="p-3">Target Resource</th>
                <th className="p-3">Correlation ID</th>
                <th className="p-3">Outcome</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/80">
              {filteredLogs.map((log) => (
                <tr key={log.id} className="hover:bg-slate-900/40">
                  <td className="p-3 text-cyan-400 font-bold">{log.id}</td>
                  <td className="p-3 text-slate-400">
                    {new Date(log.timestamp).toLocaleTimeString()}
                  </td>
                  <td className="p-3 text-white font-semibold">{log.action}</td>
                  <td className="p-3 text-slate-300">{log.actor}</td>
                  <td className="p-3 text-slate-300 max-w-xs truncate">{log.targetResource}</td>
                  <td className="p-3 text-slate-400">{log.correlationId}</td>
                  <td className="p-3">
                    <Badge
                      variant={
                        log.outcome === "SUCCESS"
                          ? "success"
                          : log.outcome === "INTERCEPTED"
                          ? "warning"
                          : "critical"
                      }
                    >
                      {log.outcome}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
