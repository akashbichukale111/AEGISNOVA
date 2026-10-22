import { NextRequest, NextResponse } from "next/server";
import {
  startAutonomousRun,
  getAllAgentRuns,
  getAgentRun
} from "@/lib/autonomous-engineering/runner";
import { RepositoryTarget, IssueTask } from "@/contracts";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const runId = url.searchParams.get("runId");

  if (runId) {
    const run = getAgentRun(runId);
    if (!run) {
      return NextResponse.json({ error: "Run not found" }, { status: 404 });
    }
    return NextResponse.json({ status: "ok", run });
  }

  const runs = getAllAgentRuns();
  return NextResponse.json({ status: "ok", runs, total: runs.length });
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const {
      repoTarget,
      issueTask,
      nebiusApiKey,
      nvidiaApiKey
    }: {
      repoTarget?: RepositoryTarget;
      issueTask?: IssueTask;
      nebiusApiKey?: string;
      nvidiaApiKey?: string;
    } = body;

    const defaultRepo: RepositoryTarget = repoTarget || {
      id: "demo/payments-service",
      name: "payments-service",
      path: "services/nightshift-sde/fixtures/demo-repos/payments-service",
      defaultBranch: "main",
      testCommand: "python -m unittest discover -s tests",
      buildManifest: "requirements.txt",
      isMonitored: true
    };

    const defaultIssue: IssueTask = issueTask || {
      id: "ISSUE-PCPR-01",
      title: "Remediate SQL parameter binding vulnerability and preserve dependency integrity",
      description: "Replace string interpolation in user query with parameterized SQL binding to mitigate CWE-89 SQL injection risk. Verify zero test regression.",
      targetRepoId: defaultRepo.id,
      acceptanceCriteria: [
        "Parameterize DB query binding in app/__init__.py",
        "Pass all existing unit tests in tests/test_app.py",
        "Zero secrets or security regressions introduced"
      ],
      severity: "HIGH",
      autonomyMode: "PATCH_AND_VERIFY",
      allowHighRiskWrites: true
    };

    const run = await startAutonomousRun({
      repoTarget: defaultRepo,
      issueTask: defaultIssue,
      nebiusApiKey: nebiusApiKey || process.env.NEBIUS_API_KEY,
      nvidiaApiKey: nvidiaApiKey || process.env.NVIDIA_API_KEY
    });

    return NextResponse.json({
      status: "ok",
      runId: run.id,
      run
    }, { status: 201 });
  } catch (error) {
    return NextResponse.json({
      error: "Failed to initiate autonomous engineering run",
      details: (error as Error).message
    }, { status: 500 });
  }
}
