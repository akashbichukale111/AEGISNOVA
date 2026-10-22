import { NextRequest, NextResponse } from "next/server";
import {
  NVIDIA_DEFAULT_TELEMETRY,
  synthesizePatchWithNvidiaNim,
  evaluateNeMoGuardrails
} from "@/lib/nvidia-nim";

export const dynamic = "force-dynamic";

export async function GET() {
  const isKeyConfigured = Boolean(process.env.NVIDIA_API_KEY);
  return NextResponse.json({
    status: "ok",
    provider: "NVIDIA NIM (Inference Microservices)",
    acceleration: isKeyConfigured ? "LIVE_NVIDIA_CLOUD_NIM" : "TENSORRT_ACCELERATED_DEMO",
    hardware: NVIDIA_DEFAULT_TELEMETRY,
    supportedModels: [
      "nvidia/nemotron-4-340b-instruct",
      "meta/llama-3.1-70b-instruct",
      "nvidia/llama-3.2-nv-embedqa-1b"
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
