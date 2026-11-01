import { NextRequest, NextResponse } from "next/server";
import { approveAndExecuteIncident } from "@/lib/copilot/engine";

export const dynamic = "force-dynamic";

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { incidentId } = body;

    if (!incidentId || typeof incidentId !== "string") {
      return NextResponse.json(
        { error: "Missing or invalid 'incidentId' in request body." },
        { status: 400 }
      );
    }

    const result = await approveAndExecuteIncident(incidentId);
    if (!result.success) {
      return NextResponse.json(result, { status: 404 });
    }

    return NextResponse.json(result);
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}
