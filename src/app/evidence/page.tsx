"use client";

import React, { useState, useEffect } from "react";
import {
  FileSearch,
  Sparkles,
  Layers,
  ShieldCheck,
  Database,
  Search,
  CheckCircle2,
  AlertTriangle,
  RefreshCw,
  Clock,
  ExternalLink,
  Zap,
  Globe,
  BookOpen,
  ArrowRight,
  TrendingUp,
  Cpu
} from "lucide-react";
import { Card } from "../../components/ui/Card";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";

interface TavilyResultItem {
  title: string;
  url: string;
  content: string;
  score: number;
  publishedDate?: string;
}

interface EvidenceSearchResponse {
  query: string;
  answer?: string;
  results: TavilyResultItem[];
  responseTimeMs: number;
  provider: string;
}

const PRESET_QUERIES = [
  { label: "XZ Backdoor", query: "CVE-2024-3094 xz backdoor security advisory remote code execution" },
  { label: "Log4Shell", query: "CVE-2021-44228 Log4j JNDI remote code execution remediation" },
  { label: "aiohttp Smuggling", query: "CVE-2023-47627 aiohttp HTTP request smuggling mitigation" },
  { label: "SQL Injection CWE-89", query: "SQL injection CWE-89 parameterized query best practices python" },
  { label: "PyPI Supply Chain", query: "PyPI supply chain dependency hijacking protestware mitigation" }
];

export default function EvidenceCenterPage() {
  const [searchQuery, setSearchQuery] = useState("CVE-2024-3094 xz backdoor security advisory");
  const [isResearching, setIsResearching] = useState(false);
  const [searchResult, setSearchResult] = useState<EvidenceSearchResponse | null>(null);
  const [recentSearches, setRecentSearches] = useState<string[]>([
    "CVE-2024-3094 xz backdoor",
    "CVE-2023-47627 aiohttp",
    "SQL injection CWE-89"
  ]);

  // Execute initial search on mount
  useEffect(() => {
    handleSearch("CVE-2024-3094 xz backdoor security advisory");
  }, []);

  const handleSearch = async (queryToSearch: string = searchQuery) => {
    if (!queryToSearch.trim()) return;
    setIsResearching(true);

    try {
      const res = await fetch("/api/evidence/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: queryToSearch, maxResults: 5 })
      });

      if (res.ok) {
        const data = await res.json();
        setSearchResult(data);
        if (!recentSearches.includes(queryToSearch.slice(0, 30))) {
          setRecentSearches([queryToSearch.slice(0, 30), ...recentSearches.slice(0, 4)]);
        }
      }
    } catch (err) {
      console.error("Evidence search error:", err);
    } finally {
      setIsResearching(false);
    }
  };

  return (
    <div className="space-y-6 max-w-7xl mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-[#172235] pb-5">
        <div>
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-cyan-500 to-blue-700 flex items-center justify-center shadow-lg shadow-cyan-950/40 ring-1 ring-cyan-400/30">
              <FileSearch className="h-5 w-5 text-cyan-100" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold tracking-tight text-white">Tavily AI Evidence Intelligence</h1>
                <Badge variant="connected">LIVE RESEARCH ENGINE</Badge>
                <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/80 flex items-center gap-1">
                  <Globe className="h-3 w-3 text-cyan-400" />
                  Tavily AI • 300,000 Quota
                </span>
              </div>
              <p className="text-xs text-slate-400 mt-0.5">
                Real-Time Multi-Source Security Advisory Research, NIST/GHSA Reconciliation & Proof Citation
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <div className="text-xs font-mono text-slate-400 flex items-center gap-2 bg-[#0B0F19] px-3 py-1.5 rounded-lg border border-[#172235]">
            <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
            <span>Tavily Connected</span>
          </div>
        </div>
      </div>

      {/* Query Bar & Presets */}
      <Card className="p-5 bg-[#0B0F19] border-[#172235] space-y-3">
        <div className="flex flex-col sm:flex-row gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-500" />
            <input
              type="text"
              placeholder="Query any CVE, package, or vulnerability advisory (e.g. CVE-2024-3094, aiohttp smuggling, CWE-89)..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch(searchQuery)}
              className="w-full bg-[#070A10] border border-[#172235] rounded-lg pl-10 pr-4 py-2 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-cyan-500 font-mono"
            />
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => handleSearch(searchQuery)}
            disabled={isResearching}
            className="text-xs bg-cyan-600 hover:bg-cyan-500 text-white flex items-center gap-1.5 font-mono shrink-0"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${isResearching ? "animate-spin" : ""}`} />
            {isResearching ? "Searching Tavily Web..." : "Research with Tavily"}
          </Button>
        </div>

        {/* Quick Presets */}
        <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-[#172235]">
          <span className="text-[11px] font-mono text-slate-500 flex items-center gap-1">
            <Sparkles className="h-3 w-3 text-cyan-400" /> Presets:
          </span>
          {PRESET_QUERIES.map((p) => (
            <button
              key={p.label}
              onClick={() => {
                setSearchQuery(p.query);
                handleSearch(p.query);
              }}
              className="text-[11px] font-mono px-2 py-0.5 rounded bg-[#070A10] hover:bg-cyan-950/60 text-slate-300 hover:text-cyan-300 border border-[#172235] transition-all"
            >
              {p.label}
            </button>
          ))}
        </div>
      </Card>

      {/* Main Grid: AI Answer Synthesis & Cited Intelligence */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column (8 Cols): Synthesized Advisory & Evidence Results */}
        <div className="lg:col-span-8 space-y-4">
          {/* Tavily AI Synthesized Answer Card */}
          {searchResult?.answer && (
            <Card className="p-5 bg-[#0B0F19] border-cyan-900/50 space-y-3 shadow-lg shadow-cyan-950/20">
              <div className="flex items-center justify-between border-b border-[#172235] pb-2.5">
                <div className="flex items-center gap-2 text-xs font-mono text-cyan-300 font-semibold">
                  <Sparkles className="h-4 w-4 text-cyan-400" />
                  <span>Tavily AI Synthesized Security Intelligence</span>
                </div>
                <span className="text-[10px] font-mono text-slate-500">
                  Latency: {searchResult.responseTimeMs}ms
                </span>
              </div>

              <div className="text-xs text-slate-200 leading-relaxed font-sans bg-[#070A10] p-4 rounded-lg border border-[#172235]">
                {searchResult.answer}
              </div>
            </Card>
          )}

          {/* Cited Evidence Cards */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-mono font-semibold uppercase tracking-wider text-slate-300 flex items-center gap-2">
                <BookOpen className="h-4 w-4 text-cyan-400" />
                <span>Verified External Citations ({searchResult?.results?.length || 0})</span>
              </h3>
              <span className="text-[11px] font-mono text-slate-500">
                Source: Real Web Intelligence
              </span>
            </div>

            {!searchResult?.results || searchResult.results.length === 0 ? (
              <Card className="p-8 text-center text-slate-500 font-mono text-xs">
                No citations returned. Enter a search query above.
              </Card>
            ) : (
              searchResult.results.map((r, idx) => (
                <Card
                  key={idx}
                  className="p-4 bg-[#0B0F19] border-[#172235] hover:border-cyan-800/60 transition-all space-y-2.5"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-cyan-950 text-cyan-300 border border-cyan-800">
                          #{idx + 1}
                        </span>
                        <h4 className="text-xs font-bold text-white leading-snug">
                          {r.title}
                        </h4>
                      </div>
                      <a
                        href={r.url}
                        target="_blank"
                        rel="noreferrer"
                        className="text-[11px] font-mono text-cyan-400 hover:text-cyan-300 flex items-center gap-1 mt-1 truncate max-w-xl"
                      >
                        <Globe className="h-3 w-3 shrink-0" />
                        <span className="truncate">{r.url}</span>
                        <ExternalLink className="h-2.5 w-2.5 shrink-0" />
                      </a>
                    </div>

                    <div className="text-right shrink-0">
                      <span className="text-[11px] font-mono px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">
                        Score: {Math.round(r.score * 100)}%
                      </span>
                    </div>
                  </div>

                  <p className="text-xs text-slate-300 leading-relaxed bg-[#070A10] p-3 rounded border border-[#172235]">
                    {r.content}
                  </p>

                  {r.publishedDate && (
                    <div className="text-[10px] font-mono text-slate-500">
                      Published: {new Date(r.publishedDate).toLocaleDateString()}
                    </div>
                  )}
                </Card>
              ))
            )}
          </div>
        </div>

        {/* Right Column (4 Cols): Policy & Integration Telemetry */}
        <div className="lg:col-span-4 space-y-4">
          {/* Provider Card */}
          <Card className="p-4 bg-[#0B0F19] border-[#172235] space-y-3">
            <div className="flex items-center gap-2 text-xs font-mono text-white font-semibold border-b border-[#172235] pb-2">
              <Globe className="h-4 w-4 text-cyan-400" />
              <span>Tavily AI Engine Specs</span>
            </div>

            <div className="space-y-2 text-xs font-mono">
              <div className="flex justify-between text-slate-400">
                <span>Account Quota:</span>
                <span className="text-emerald-400 font-bold">300,000 requests</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Search Depth:</span>
                <span className="text-cyan-300">Advanced / Multi-hop</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Answer Synthesis:</span>
                <span className="text-emerald-400">Enabled (True)</span>
              </div>
              <div className="flex justify-between text-slate-400">
                <span>Domain Filter:</span>
                <span className="text-slate-300">NIST, GHSA, CVE, OSV</span>
              </div>
            </div>

            <div className="p-2.5 bg-[#070A10] rounded text-[11px] text-slate-400 border border-[#172235]">
              Tokens and keys are server-isolated. Every Proof-Carrying PR (PCPR) automatically reconciles citations via this service.
            </div>
          </Card>

          {/* Guarantee Box */}
          <Card className="p-4 bg-[#0B0F19] border-[#172235] space-y-2.5">
            <div className="flex items-center gap-2 text-xs font-mono text-emerald-400 font-semibold">
              <ShieldCheck className="h-4 w-4" />
              <span>Evidence Integrity Standard</span>
            </div>
            <p className="text-xs text-slate-300 leading-relaxed">
              &quot;No result does not mean safe.&quot; AEGISNOVA requires concordance between static AST scanner findings, deterministic test suites, and Tavily live web advisories before debited by UNWIND Governance.
            </p>
          </Card>

          {/* Recent Queries */}
          <Card className="p-4 bg-[#0B0F19] border-[#172235] space-y-2">
            <div className="text-xs font-mono font-semibold text-slate-300 uppercase tracking-wider">
              Recent Inquiries
            </div>
            <div className="space-y-1.5">
              {recentSearches.map((s, idx) => (
                <button
                  key={idx}
                  onClick={() => {
                    setSearchQuery(s);
                    handleSearch(s);
                  }}
                  className="w-full text-left text-[11px] font-mono p-1.5 rounded hover:bg-slate-900 text-slate-400 hover:text-cyan-300 truncate transition-colors flex items-center justify-between"
                >
                  <span className="truncate">{s}</span>
                  <ArrowRight className="h-3 w-3 shrink-0 opacity-50" />
                </button>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
