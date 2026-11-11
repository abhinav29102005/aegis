import type { Metadata } from "next";
import React from "react";
import { AuthProvider } from "@/lib/auth-context";
import "./globals.css";

export const metadata: Metadata = {
  title: "AEGIS — Financial Black Box for AI Agents",
  description:
    "Deterministic spending governance, PayPal sandbox execution controls, GhostPay counterfactual replay, and DisputeOS investigation platform.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}
