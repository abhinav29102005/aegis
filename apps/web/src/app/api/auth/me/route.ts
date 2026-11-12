import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export async function GET() {
  try {
    const cookieStore = await cookies();
    const token = cookieStore.get("aegis_session")?.value;
    const tenantId = cookieStore.get("aegis_tenant_id")?.value;

    if (!token) {
      return NextResponse.json(
        { error_code: "UNAUTHENTICATED", message: "No active session cookie found" },
        { status: 401 },
      );
    }

    const backendUrl = (process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

    const headers: Record<string, string> = {
      Authorization: `Bearer ${token}`,
    };
    if (tenantId) {
      headers["X-Org-Id"] = tenantId;
    }

    const res = await fetch(`${backendUrl}/v1/auth/me`, {
      method: "GET",
      headers,
    });

    const data = await res.json();
    if (!res.ok) {
      cookieStore.delete("aegis_session");
      cookieStore.delete("aegis_tenant_id");
      return NextResponse.json(data, { status: res.status });
    }

    // Keep active_tenant_id cookie synced
    if (data.active_tenant_id) {
      cookieStore.set({
        name: "aegis_tenant_id",
        value: data.active_tenant_id,
        httpOnly: true,
        sameSite: "lax",
        secure: process.env.NODE_ENV === "production",
        path: "/",
        maxAge: 60 * 60 * 24 * 7,
      });
    }

    // Normalize AuthSession fields for client consumption
    const normalized = {
      ...data,
      active_role: data.active_role || data.role,
      access_token: data.access_token || token,
      full_name: data.full_name || data.active_organization?.name || data.email,
    };

    return NextResponse.json(normalized, { status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error_code: "BFF_ME_ERROR", message: error instanceof Error ? error.message : "Failed to fetch user session" },
      { status: 500 },
    );
  }
}
