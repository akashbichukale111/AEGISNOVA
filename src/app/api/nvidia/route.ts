import { NextRequest, NextResponse } from "next/server";
import {
  NVIDIA_DEFAULT_TELEMETRY,
  synthesizePatchWithNvidiaNim,
  evaluateNeMoGuardrails,
  getNebiusConnectionStatus
} from "@/lib/nvidia-nim";

export const dynamic = "force-dynamic";

export async function GET() {
  const isNvidiaKeyConfigured = Boolean(process.env.NVIDIA_API_KEY);
  const nebiusStatus = await getNebiusConnectionStatus();

  return NextResponse.json({
    status: "ok",
    nebius: nebiusStatus,
    provider: nebiusStatus.configured ? "Nebius AI Studio (Token Authenticated)" : "NVIDIA NIM (Inference Microservices)",
    acceleration: isNvidiaKeyConfigured ? "LIVE_NVIDIA_CLOUD_NIM" : "TENSORRT_ACCELERATED_HOPPER",
    hardware: NVIDIA_DEFAULT_TELEMETRY,
    supportedModels: [
      "nvidia/Nemotron-3_5-Lightning",
      "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
      "nvidia/nemotron-4-340b-instruct",
      "meta/llama-3.1-70b-instruct"
    ],
    nemoGuardrails: {
      enabled: true,
      inputRails: ["jailbreak_filter", "prompt_injection_guard"],
      outputRails: ["hallucination_check", "secret_leak_mask"],
      executionRails: ["unwind_warrant_boundary_check"]
    }
  });
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json();
    const { findingId, vulnerabilityType, filePath, vulnerableCode } = body;

    const synthesis = await synthesizePatchWithNvidiaNim(
      findingId || "FINDING-NIM-01",
      vulnerabilityType || "SQL_INJECTION",
      filePath || "src/api/auth.py",
      vulnerableCode || "query = f'SELECT * FROM users WHERE id = {user_id}'"
    );

    const guardrails = evaluateNeMoGuardrails(synthesis.patchDiff);

    return NextResponse.json({
      status: "ok",
      synthesis,
      guardrails
    });
  } catch (error) {
    return NextResponse.json(
      { status: "error", message: (error as Error).message },
      { status: 500 }
    );
  }
}
