"use client";

import React, { useState } from "react";
import {
  ShieldAlert,
  Search,
  Filter,
  CheckCircle2,
  AlertTriangle,
  Play,
  FileCode,
  ArrowRight,
  GitPullRequest,
  Check,
  X,
  Code2,
} from "lucide-react";
import { Card, CardHeader } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ConfirmationModal, Modal } from "../../components/ui/Modal";
import { INITIAL_FINDINGS, INITIAL_REPOSITORIES } from "../../lib/demo-data";
import { Finding, PatchProposal, ValidationResult } from "../../contracts";

export default function SecurityCenterPage() {
  const [activeTab, setActiveTab] = useState<"scanner" | "fixer" | "validator">("scanner");
  const [findings, setFindings] = useState<Finding[]>(INITIAL_FINDINGS);
  const [selectedFinding, setSelectedFinding] = useState<Finding | null>(INITIAL_FINDINGS[0]);
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [isApplyingPatch, setIsApplyingPatch] = useState(false);
  const [appliedPatches, setAppliedPatches] = useState<Record<string, boolean>>({});

  // Simulated patch proposal
  const mockPatchProposal: PatchProposal = {
    schemaVersion: "1.0.0",
    id: "PATCH-9921",
    findingId: selectedFinding?.id || "FIND-SEC-101",
    proposedBy: "devguard-ai-fixer",
    explanation:
      "Replaces vulnerable raw string formatted query with parameterized SQLAlchemy / DB-API execution, preventing SQL injection.",
    diff: `--- a/backend/core/telemetry.py
+++ b/backend/core/telemetry.py
@@ -139,5 +139,5 @@
-cursor.execute(f"SELECT * FROM traces WHERE tenant_id = '{tenant_id}'")
+cursor.execute("SELECT * FROM traces WHERE tenant_id = %s", (tenant_id,))`,
    confidenceScore: 0.98,
    governanceRequired: true,
    applied: !!appliedPatches[selectedFinding?.id || ""],
  };

  const mockValidationResult: ValidationResult = {
    schemaVersion: "1.0.0",
    id: "VAL-881",
    patchProposalId: mockPatchProposal.id,
    syntaxValid: true,
    testSuitePassed: true,
    regressionDetected: false,
    verifiedAt: "2026-10-20T20:18:00Z",
    summary: "AST syntax analysis passed. 18 telemetry unit tests executed and passed cleanly.",
  };

  const filteredFindings = findings.filter((f) => {
    const matchesSeverity = severityFilter === "ALL" || f.severity === severityFilter;
    const matchesSearch =
      f.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      f.ruleId.toLowerCase().includes(searchQuery.toLowerCase()) ||
      f.filePath.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesSeverity && matchesSearch;
  });

  const handleApplyPatch = () => {
    if (!selectedFinding) return;
    setAppliedPatches((prev) => ({ ...prev, [selectedFinding.id]: true }));
    setFindings((prev) =>
      prev.map((f) => (f.id === selectedFinding.id ? { ...f, status: "RESOLVED" } : f))
    );
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold text-white tracking-tight">Security Center</h1>
            <Badge variant="demo">DEMO / RESILIENT ADAPTER</Badge>
          </div>
          <p className="text-xs text-slate-400 mt-1">
            DevGuard AI Scanner → Resilient Fixer → Validator with UNWIND Governance Gate
          </p>
        </div>

        {/* Tab Controls */}
        <div className="flex items-center gap-1.5 p-1 rounded-xl bg-slate-900 border border-slate-800">
          <button
            onClick={() => setActiveTab("scanner")}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === "scanner"
                ? "bg-cyan-600 text-white shadow"
                : "text-slate-400 hover:text-white"
            }`}
          >
            1. Scanner ({filteredFindings.length})
          </button>
          <button
            onClick={() => setActiveTab("fixer")}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === "fixer"
                ? "bg-cyan-600 text-white shadow"
                : "text-slate-400 hover:text-white"
            }`}
          >
            2. Fixer (Patch Proposal)
          </button>
          <button
            onClick={() => setActiveTab("validator")}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
              activeTab === "validator"
                ? "bg-cyan-600 text-white shadow"
                : "text-slate-400 hover:text-white"
            }`}
          >
            3. Validator
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      {activeTab === "scanner" && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Left Column: Filterable Findings List (7 cols) */}
          <div className="lg:col-span-7 space-y-4">
            <Card>
              <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3 mb-4">
                {/* Search */}
                <div className="relative flex-1">
                  <Search className="absolute left-3 top-2.5 h-4 w-4 text-slate-500" />
                  <input
                    type="text"
                    placeholder="Search findings, rules, files..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="w-full pl-9 pr-3 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-white focus:outline-none focus:border-cyan-500 font-mono"
                  />
                </div>

                {/* Severity Dropdown */}
                <div className="flex items-center gap-2">
                  <Filter className="h-3.5 w-3.5 text-slate-400" />
                  <select
                    value={severityFilter}
                    onChange={(e) => setSeverityFilter(e.target.value)}
                    aria-label="Filter findings by severity"
                    className="px-2.5 py-2 rounded-lg bg-slate-900 border border-slate-800 text-xs text-slate-300 font-mono focus:outline-none"
                  >
                    <option value="ALL">All Severities</option>
                    <option value="CRITICAL">Critical</option>
                    <option value="HIGH">High</option>
                    <option value="MEDIUM">Medium</option>
                    <option value="LOW">Low</option>
                  </select>
                </div>
              </div>

              {/* Findings List */}
              <div className="space-y-2.5">
                {filteredFindings.map((finding) => {
                  const isSelected = selectedFinding?.id === finding.id;
                  return (
                    <div
                      key={finding.id}
                      onClick={() => setSelectedFinding(finding)}
                      className={`p-3.5 rounded-xl border cursor-pointer transition-all ${
                        isSelected
                          ? "bg-cyan-950/40 border-cyan-500/70 shadow-[0_0_12px_rgba(6,182,212,0.1)]"
                          : "bg-slate-900/60 border-slate-800/80 hover:bg-slate-900 hover:border-slate-700"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="space-y-1">
                          <div className="flex items-center gap-2">
                            <Badge variant={finding.severity.toLowerCase() as any}>
                              {finding.severity}
                            </Badge>
                            <span className="font-mono text-xs text-slate-300 font-semibold">
                              {finding.ruleId}
                            </span>
                            <span className="text-xs text-slate-500">•</span>
                            <span className="text-[11px] font-mono text-slate-400">
                              {finding.id}
                            </span>
                          </div>
                          <h4 className="text-sm font-semibold text-white">{finding.title}</h4>
                          <p className="text-xs text-slate-400 line-clamp-1">{finding.description}</p>
                        </div>

                        <Badge
                          variant={finding.status === "RESOLVED" ? "success" : "neutral"}
                          size="sm"
                        >
                          {finding.status}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            </Card>
          </div>

          {/* Right Column: Finding Detail Drawer (5 cols) */}
          <div className="lg:col-span-5">
            {selectedFinding ? (
              <Card className="sticky top-20 space-y-4">
                <div className="flex items-start justify-between border-b border-slate-800 pb-3">
                  <div>
                    <span className="font-mono text-xs text-cyan-400">{selectedFinding.id}</span>
                    <h3 className="text-base font-bold text-white mt-0.5">{selectedFinding.title}</h3>
                  </div>
                  <Badge variant={selectedFinding.severity.toLowerCase() as any}>
                    {selectedFinding.severity}
                  </Badge>
                </div>

                <div className="space-y-2">
                  <span className="text-xs font-mono uppercase text-slate-400">Location</span>
                  <div className="p-2.5 rounded-lg bg-slate-900 font-mono text-xs text-slate-200 border border-slate-800">
                    {selectedFinding.filePath}:{selectedFinding.lineNumber}
                  </div>
                </div>

                <div className="space-y-2">
                  <span className="text-xs font-mono uppercase text-slate-400">Vulnerable Snippet</span>
                  <pre className="p-3 rounded-lg bg-black/60 border border-red-900/40 text-red-300 font-mono text-xs overflow-x-auto">
                    <code>{selectedFinding.codeSnippet}</code>
                  </pre>
                </div>

                <div className="space-y-2">
                  <span className="text-xs font-mono uppercase text-slate-400">Description</span>
                  <p className="text-xs text-slate-300 leading-relaxed">
                    {selectedFinding.description}
                  </p>
                </div>

                <div className="pt-3 border-t border-slate-800 flex items-center justify-between">
                  <Button
                    variant="primary"
                    size="sm"
                    icon={<FileCode className="h-4 w-4" />}
                    onClick={() => setActiveTab("fixer")}
                  >
                    Generate / View Patch
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setActiveTab("validator")}
                  >
                    Run Validator
                  </Button>
                </div>
              </Card>
            ) : (
              <Card className="p-12 text-center text-slate-500 font-mono text-xs">
                Select a finding from the list to view AST details.
              </Card>
            )}
          </div>
        </div>
      )}

      {/* Tab 2: Fixer (Patch Proposal with Diff View) */}
      {activeTab === "fixer" && (
        <Card className="space-y-6">
          <CardHeader
            title="DevGuard Resilient Fixer & Patch Proposal"
            subtitle={`Proposed remediation for finding ${selectedFinding?.id || "N/A"}`}
            badge={<Badge variant="demo">DEMO PATCH</Badge>}
            action={
              <Button
                variant={appliedPatches[selectedFinding?.id || ""] ? "secondary" : "danger"}
                size="md"
                disabled={appliedPatches[selectedFinding?.id || ""]}
                onClick={() => setIsApplyingPatch(true)}
              >
                {appliedPatches[selectedFinding?.id || ""] ? "Patch Applied (Resolved)" : "Apply Patch with Governance"}
              </Button>
            }
          />

          <div className="space-y-4">
            <div className="p-4 rounded-xl bg-slate-900/80 border border-slate-800 space-y-2">
              <span className="text-xs font-mono uppercase text-cyan-400 font-semibold">
                Explanation & Rationale
              </span>
              <p className="text-sm text-slate-200">{mockPatchProposal.explanation}</p>
              <div className="flex items-center gap-4 text-xs font-mono text-slate-400 pt-1">
                <span>Confidence: {(mockPatchProposal.confidenceScore * 100).toFixed(0)}%</span>
                <span>Proposed By: {mockPatchProposal.proposedBy}</span>
                <span>Governance Required: Yes</span>
              </div>
            </div>

            {/* Side-by-side Unified Diff */}
            <div className="space-y-2">
              <div className="flex items-center justify-between text-xs font-mono text-slate-400">
                <span>Unified Diff Proposal</span>
                <span>backend/core/telemetry.py</span>
              </div>
              <pre className="p-4 rounded-xl bg-black/80 border border-slate-800 text-xs font-mono text-slate-200 overflow-x-auto leading-relaxed">
                <code>{mockPatchProposal.diff}</code>
              </pre>
            </div>
          </div>
        </Card>
      )}

      {/* Tab 3: Validator */}
      {activeTab === "validator" && (
        <Card className="space-y-6">
          <CardHeader
            title="Validator Results & Gate Proof"
            subtitle="Deterministic verification of proposed code patch"
            badge={<Badge variant="success">PASSED</Badge>}
          />

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-900/40 space-y-1">
              <div className="flex items-center gap-2 text-emerald-400 font-semibold text-xs">
                <Check className="h-4 w-4" /> Syntax Validation
              </div>
              <p className="text-xs text-slate-300">AST parsing succeeded with zero syntax errors.</p>
            </div>
            <div className="p-4 rounded-xl bg-emerald-950/20 border border-emerald-900/40 space-y-1">
              <div className="flex items-center gap-2 text-emerald-400 font-semibold text-xs">
                <Check className="h-4 w-4" /> Unit Test Suite
              </div>
              <p className="text-xs text-slate-300">18 test cases executed, 0 regressions detected.</p>
            </div>
            <div className="p-4 rounded-xl bg-cyan-950/20 border border-cyan-900/40 space-y-1">
              <div className="flex items-center gap-2 text-cyan-400 font-semibold text-xs">
                <ShieldAlert className="h-4 w-4" /> Security Guarantee
              </div>
              <p className="text-xs text-slate-300">Parameterized query eliminates CWE-89 completely.</p>
            </div>
          </div>

          <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 text-xs font-mono text-slate-400 space-y-1">
            <div className="text-slate-300 font-semibold">Verification Audit Log:</div>
            <div>{mockValidationResult.summary}</div>
            <div className="text-slate-500">Timestamp: {mockValidationResult.verifiedAt}</div>
          </div>
        </Card>
      )}

      {/* Confirmation Modal before applying sensitive patch */}
      <ConfirmationModal
        isOpen={isApplyingPatch}
        onClose={() => setIsApplyingPatch(false)}
        onConfirm={handleApplyPatch}
        title="Confirm Remediation Patch Application"
        message={`Applying this patch will mutate file '${selectedFinding?.filePath}'. UNWIND Governance requires scoped human confirmation before any write to disk.`}
        confirmLabel="Authorize Patch Application"
        confirmVariant="danger"
        riskBadge="HIGH RISK FILE MUTATION"
      />
    </div>
  );
}
