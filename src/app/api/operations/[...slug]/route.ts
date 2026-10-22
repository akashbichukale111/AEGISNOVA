import { NextRequest, NextResponse } from "next/server";
import fs from "fs";
import path from "path";

const OPERATIONS_SERVICE_URL = process.env.OPERATIONS_SERVICE_URL || "http://127.0.0.1:8080";

function getInternalToken(): string {
  // If explicitly provided via environment, prioritize it
  if (process.env.OPERATIONS_INTERNAL_TOKEN && process.env.OPERATIONS_INTERNAL_TOKEN !== "secret-internal-proxy-token") {
    return process.env.OPERATIONS_INTERNAL_TOKEN;
  }
  // Otherwise read the generated dev token from the service's local store
  const tokenFilePath = path.join(process.cwd(), "services", "autonomous-operations", ".local", "dev-tokens.json");
  if (fs.existsSync(tokenFilePath)) {
    try {
      const data = JSON.parse(fs.readFileSync(tokenFilePath, "utf8"));
      if (data.admin) return data.admin;
    } catch {}
  }
  return process.env.OPERATIONS_INTERNAL_TOKEN || "secret-internal-proxy-token";
}

export async function GET(
  request: NextRequest,
  { params }: { params: { slug: string[] } }
) {
  const pathPart = params.slug ? params.slug.join("/") : "";
  const searchParams = request.nextUrl.searchParams.toString();
  const targetUrl = `${OPERATIONS_SERVICE_URL}/api/${pathPart}${searchParams ? `?${searchParams}` : ""}`;
  const token = getInternalToken();

  try {
    const res = await fetch(targetUrl, {
      method: "GET",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      cache: "no-store",
    });

    const data = await res.json().catch(() => null);
    return NextResponse.json(data, { status: res.status });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: {
          code: "OPERATIONS_SERVICE_UNAVAILABLE",
          message: "Internal Python autonomous operations service is currently offline or unreachable at " + OPERATIONS_SERVICE_URL,
          suggestion: "Start the service with: python -m aegisnova_ops inside services/autonomous-operations",
        },
      },
      { status: 503 }
    );
  }
}

export async function POST(
  request: NextRequest,
  { params }: { params: { slug: string[] } }
) {
  const pathPart = params.slug ? params.slug.join("/") : "";
  const targetUrl = `${OPERATIONS_SERVICE_URL}/api/${pathPart}`;
  const token = getInternalToken();

  try {
    const body = await request.json().catch(() => ({}));
    const res = await fetch(targetUrl, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    const data = await res.json().catch(() => null);
    return NextResponse.json(data, { status: res.status });
  } catch (err: any) {
    return NextResponse.json(
      {
        error: {
          code: "OPERATIONS_SERVICE_UNAVAILABLE",
          message: "Internal Python autonomous operations service is currently offline.",
        },
      },
      { status: 503 }
    );
  }
}
