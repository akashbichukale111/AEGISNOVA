import { NextRequest, NextResponse } from "next/server";
import {
  processCopilotMessage,
  getAllIncidents,
  getAllRecurrentMemories
} from "@/lib/copilot/engine";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    const incidents = getAllIncidents();
    const memories = getAllRecurrentMemories();
    return NextResponse.json({
      status: "ok",
      incidents,
      memories,
      stats: {
        totalIncidents: incidents.length,
        autoResolvedNoWakeup: incidents.filter(i => i.action === "AUTO_RESOLVED_NO_SDE_WAKEUP").length,
        recurrentHealedFromMemory: incidents.filter(i => i.action === "RECURRENT_HEALED_FROM_MEMORY").length,
        waitingForSdeApproval: incidents.filter(i => i.action === "WAITING_FOR_SDE_APPROVAL").length,
        sdeApproved: incidents.filter(i => i.action === "SDE_APPROVED_AND_EXECUTED").length,
        activeMemoryPatterns: memories.length
      }
    });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { message, repoUrl } = body;

    if (!message || typeof message !== "string") {
      return NextResponse.json(
        { error: "Missing or invalid 'message' in request body." },
        { status: 400 }
      );
    }

    const reply = await processCopilotMessage(message, repoUrl);
    return NextResponse.json({ reply });
  } catch (error) {
    return NextResponse.json({ error: (error as Error).message }, { status: 500 });
  }
}
