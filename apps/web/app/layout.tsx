import type { Metadata } from "next";
import {
  Instrument_Sans,
  Instrument_Serif,
  JetBrains_Mono,
} from "next/font/google";
import { SessionProvider } from "next-auth/react";
import "./globals.css";

// The three variables are what globals.css's --font-sans/serif/mono resolve
// to; renaming one here breaks every family token.
const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-instrument-sans",
  display: "swap",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  style: ["normal", "italic"],
  variable: "--font-instrument-serif",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Hax",
  description: "AI-first chat over your data",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${instrumentSans.variable} ${instrumentSerif.variable} ${jetbrainsMono.variable}`}
    >
      <body>
        {/* basePath must match auth.ts ("/auth") or the client helpers call
            the wrong endpoints. */}
        <SessionProvider basePath="/auth">{children}</SessionProvider>
        {/* Chrome on Android can keep a stale, zoomed-out page scale when the
            system theme changes with the tab open; one fixed-position element
            in the page is enough to make it settle. Inert and invisible: do
            not remove it as dead markup. */}
        <div
          aria-hidden="true"
          className="pointer-events-none fixed bottom-0 left-0 size-px"
        />
      </body>
    </html>
  );
}
