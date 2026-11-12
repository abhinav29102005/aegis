import { cookies } from "next/headers";
import { type NextRequest, NextResponse } from "next/server";

async function proxyRequest(request: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  try {
    const { path } = await params;
    const subpath = path.join("/");
    const backendUrl = (process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

    const url = new URL(request.url);
    const targetUrl = `${backendUrl}/v1/${subpath}${url.search}`;

    const cookieStore = await cookies();
    const token = cookieStore.get("aegis_session")?.value;
    const tenantCookie = cookieStore.get("aegis_tenant_id")?.value;

    const headers = new Headers();
    const contentType = request.headers.get("content-type");
    if (contentType) {
      headers.set("content-type", contentType);
    }
    const accept = request.headers.get("accept");
    if (accept) {
      headers.set("accept", accept);
    }
    const correlationId = request.headers.get("x-correlation-id");
    if (correlationId) {
      headers.set("x-correlation-id", correlationId);
    }
    const idempotencyKey = request.headers.get("x-idempotency-key");
    if (idempotencyKey) {
      headers.set("x-idempotency-key", idempotencyKey);
    }

    if (token) {
      headers.set("authorization", `Bearer ${token}`);
    }

    const orgId = request.headers.get("x-org-id") || tenantCookie;
    if (orgId) {
      headers.set("x-org-id", orgId);
    }

    let body: BodyInit | null = null;
    if (request.method !== "GET" && request.method !== "HEAD") {
      body = await request.arrayBuffer();
    }

    const res = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
    });

    const responseData = await res.arrayBuffer();
    const responseHeaders = new Headers();
    const resContentType = res.headers.get("content-type");
    if (resContentType) {
      responseHeaders.set("content-type", resContentType);
    }

    // Auto-evict session on 401
    if (res.status === 401) {
      cookieStore.delete("aegis_session");
      cookieStore.delete("aegis_tenant_id");
    }

    return new NextResponse(responseData, {
      status: res.status,
      headers: responseHeaders,
    });
  } catch (error) {
    return NextResponse.json(
      { error_code: "BFF_PROXY_ERROR", message: error instanceof Error ? error.message : "Failed to proxy request" },
      { status: 502 },
    );
  }
}

export const GET = proxyRequest;
export const POST = proxyRequest;
export const PUT = proxyRequest;
export const PATCH = proxyRequest;
export const DELETE = proxyRequest;
export const HEAD = proxyRequest;
export const OPTIONS = proxyRequest;
