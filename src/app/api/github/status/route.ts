import { NextRequest, NextResponse } from "next/server";
import { getGitHubConnectionStatus, verifyRepositoryAccess } from "@/lib/github/client";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const status = await getGitHubConnectionStatus();
    return NextResponse.json(status);
  } catch (error) {
    return NextResponse.json(
      { status: "UNCONFIGURED", tokenConfigured: false, error: (error as Error).message },
      { status: 500 }
    );
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { url } = body;

    if (!url || typeof url !== "string") {
      return NextResponse.json({ error: "Missing or invalid repository 'url' in request body." }, { status: 400 });
    }

    const verification = await verifyRepositoryAccess(url);
    return NextResponse.json(verification);
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}
