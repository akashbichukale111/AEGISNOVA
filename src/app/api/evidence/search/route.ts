import { NextRequest, NextResponse } from "next/server";
import { searchSecurityEvidence, getTavilyStatus } from "@/lib/evidence/tavily";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest) {
  try {
    const { searchParams } = new URL(req.url);
    const q = searchParams.get("q");

    if (!q) {
      const status = await getTavilyStatus();
      return NextResponse.json(status);
    }

    const maxResults = parseInt(searchParams.get("max") || "4", 10);
    const results = await searchSecurityEvidence(q, maxResults);
    return NextResponse.json(results);
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error).message },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const query = body.query || body.q;

    if (!query || typeof query !== "string") {
      return NextResponse.json(
        { error: "Missing required 'query' in request body." },
        { status: 400 }
      );
    }

    const maxResults = typeof body.maxResults === "number" ? body.maxResults : 4;
    const evidence = await searchSecurityEvidence(query, maxResults);
    return NextResponse.json(evidence);
  } catch (error) {
    return NextResponse.json(
      { error: (error as Error).message },
      { status: 500 }
    );
  }
}
