import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const orgId = body.organization_id || body.orgId;

    if (!orgId) {
      return NextResponse.json({ error_code: "INVALID_PARAM", message: "organization_id is required" }, { status: 400 });
    }

    const cookieStore = await cookies();
    const token = cookieStore.get("aegis_session")?.value;

    if (!token) {
      return NextResponse.json({ error_code: "UNAUTHENTICATED", message: "No active session cookie found" }, { status: 401 });
    }

    const backendUrl = (process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

    const res = await fetch(`${backendUrl}/v1/auth/me`, {
      method: "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        "X-Org-Id": orgId,
      },
    });

    const data = await res.json();
    if (!res.ok) {
      return NextResponse.json(data, { status: res.status });
    }

    cookieStore.set({
      name: "aegis_tenant_id",
      value: orgId,
      httpOnly: true,
      sameSite: "lax",
      secure: process.env.NODE_ENV === "production",
      path: "/",
      maxAge: 60 * 60 * 24 * 7,
    });

    const normalized = {
      ...data,
      active_tenant_id: orgId,
      active_role: data.active_role || data.role,
      access_token: data.access_token || token,
      full_name: data.full_name || data.active_organization?.name || data.email,
    };

    return NextResponse.json(normalized, { status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error_code: "BFF_SWITCH_ORG_ERROR", message: error instanceof Error ? error.message : "Failed to switch organization" },
      { status: 500 },
    );
  }
}
