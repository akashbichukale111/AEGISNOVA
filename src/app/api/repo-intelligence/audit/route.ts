import { NextRequest, NextResponse } from "next/server";
import { analyzeRepository } from "@/lib/repo-intelligence/analyzer";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const target = body.url || body.repoTargetId || body.repo;

    if (!target || typeof target !== "string") {
      return NextResponse.json({ error: "Missing required 'url' or 'repoTargetId' in request body." }, { status: 400 });
    }

    const report = await analyzeRepository(target);
    return NextResponse.json(report);
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}
