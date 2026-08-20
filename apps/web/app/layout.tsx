import type { Metadata } from "next";
import { SessionProvider } from "next-auth/react";
import "./globals.css";

export const metadata: Metadata = {
  title: "hax",
  description: "AI-first chat over your data",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        {/* basePath must match auth.ts ("/auth") or the client helpers call
            the wrong endpoints. */}
        <SessionProvider basePath="/auth">{children}</SessionProvider>
      </body>
    </html>
  );
}
