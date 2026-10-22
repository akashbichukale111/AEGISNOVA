import { NextResponse } from "next/server";
import { listAvailableRepositories } from "@/lib/github/client";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const repos = await listAvailableRepositories();
    return NextResponse.json({ repos });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}
