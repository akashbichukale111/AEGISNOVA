import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const NIGHTSHIFT_BACKEND_URL = process.env.NIGHTSHIFT_BACKEND_URL || "http://127.0.0.1:8787";

export const dynamic = "force-dynamic";

function getNightShiftAdminToken(): string | null {
  try {
    const tokenPath = path.resolve(process.cwd(), "services/nightshift-sde/data/local-tokens.json");
    if (fs.existsSync(tokenPath)) {
      const raw = fs.readFileSync(tokenPath, "utf-8");
      const tokens = JSON.parse(raw);
      return tokens.admin?.token || tokens.operator?.token || null;
    }
  } catch (err) {
    console.warn("[NightShift Proxy] Could not load token file:", err);
  }
  return process.env.NIGHTSHIFT_ADMIN_TOKEN || null;
}

export async function GET(
  req: NextRequest,
  { params }: { params: { slug?: string[] } }
) {
  return handleProxy(req, params.slug || [], "GET");
}

export async function POST(
  req: NextRequest,
  { params }: { params: { slug?: string[] } }
) {
  return handleProxy(req, params.slug || [], "POST");
}

export async function PATCH(
  req: NextRequest,
  { params }: { params: { slug?: string[] } }
) {
  return handleProxy(req, params.slug || [], "PATCH");
}

export async function DELETE(
  req: NextRequest,
  { params }: { params: { slug?: string[] } }
) {
  return handleProxy(req, params.slug || [], "DELETE");
}

async function handleProxy(
  req: NextRequest,
  slugParts: string[],
  method: string
) {
  const subpath = slugParts.join("/");
  const url = new URL(req.url);
  const targetUrl = `${NIGHTSHIFT_BACKEND_URL}/api/${subpath}${url.search}`;

  const token = getNightShiftAdminToken();
  const headers: Record<string, string> = {
    "Accept": "application/json",
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const idempotencyKey = req.headers.get("idempotency-key");
  if (idempotencyKey) {
    headers["Idempotency-Key"] = idempotencyKey;
  }

  let body: string | undefined = undefined;
  if (method === "POST" || method === "PATCH") {
    try {
      const text = await req.text();
      if (text) {
        body = text;
        headers["Content-Type"] = "application/json";
      }
    } catch {
      // ignore
    }
  }

  try {
    const backendRes = await fetch(targetUrl, {
      method,
      headers,
      body,
      cache: "no-store",
    });

    const resContentType = backendRes.headers.get("content-type") || "";
    if (resContentType.includes("application/json")) {
      const data = await backendRes.json();
      return NextResponse.json(data, { status: backendRes.status });
    }

    const text = await backendRes.text();
    return new NextResponse(text, {
      status: backendRes.status,
      headers: { "Content-Type": resContentType || "text/plain" },
    });
  } catch (err: unknown) {
    return NextResponse.json(
      {
        error: {
          code: "NIGHTSHIFT_BACKEND_OFFLINE",
          message: "NightShift SDE backend is currently unreachable on 127.0.0.1:8787",
          details: (err as Error).message,
        },
        service: "nightshift",
        state: "OFFLINE",
      },
      { status: 503 }
    );
  }
}
