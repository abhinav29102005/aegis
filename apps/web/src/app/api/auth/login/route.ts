import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const backendUrl = (process.env.API_BASE_URL || process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

    const res = await fetch(`${backendUrl}/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

    const data = await res.json();
    const cookieStore = await cookies();

    if (!res.ok) {
      cookieStore.delete("aegis_session");
      cookieStore.delete("aegis_tenant_id");
      return NextResponse.json(data, { status: res.status });
    }

    const isSecure =
      process.env.COOKIE_SECURE === "true" ||
      (process.env.NODE_ENV === "production" &&
        (request.headers.get("x-forwarded-proto") === "https" || request.url.startsWith("https:")));

    const token = data.access_token;
    if (token) {
      cookieStore.set({
        name: "aegis_session",
        value: token,
        httpOnly: true,
        sameSite: "lax",
        secure: isSecure,
        path: "/",
        maxAge: 60 * 60 * 24 * 7, // 7 days
      });
    }

    if (data.active_tenant_id) {
      cookieStore.set({
        name: "aegis_tenant_id",
        value: data.active_tenant_id,
        httpOnly: true,
        sameSite: "lax",
        secure: isSecure,
        path: "/",
        maxAge: 60 * 60 * 24 * 7,
      });
    }

    return NextResponse.json(data, { status: 200 });
  } catch (error) {
    return NextResponse.json(
      { error_code: "BFF_LOGIN_ERROR", message: error instanceof Error ? error.message : "Failed to login" },
      { status: 500 },
    );
  }
}
