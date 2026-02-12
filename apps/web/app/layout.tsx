import type { Metadata } from "next";
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
      <body>{children}</body>
    </html>
  );
}
