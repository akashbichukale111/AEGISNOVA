import { NextRequest, NextResponse } from "next/server";
import { getAgentRun } from "@/lib/autonomous-engineering/runner";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  const runId = url.searchParams.get("runId");

  if (!runId) {
    return NextResponse.json({ error: "runId parameter required" }, { status: 400 });
  }

  const run = getAgentRun(runId);
  if (!run) {
    return NextResponse.json({ error: "Run not found" }, { status: 404 });
  }

  return NextResponse.json({
    status: "ok",
    runId: run.id,
    runStatus: run.status,
    currentStepIndex: run.currentStepIndex,
    plan: run.plan,
    events: run.events,
    changedFiles: run.changedFiles,
    manifest: run.manifest || null,
    updatedAt: run.updatedAt
  });
}
