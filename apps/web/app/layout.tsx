import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import localFont from "next/font/local";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { SIDEBAR_INIT_SCRIPT } from "@/components/layout/sidebar-prefs";
import { STYLE_INIT } from "@/features/preferences/style-prefs";

import { Providers } from "./providers";
import "./globals.css";

// Ark Pixel 12px by TakWolf — SIL Open Font License 1.1 (app/fonts/ArkPixel-OFL.txt), self-hosted,
// subset to Latin + Cyrillic + punctuation by scripts/subset-ark.py. Only the office's captions use
// it now (the interface is in the system font — owner's decision 2026-11-03).
const officeFont = localFont({
  src: "./fonts/ArkPixel12.woff2",
  variable: "--font-body",
  weight: "400",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

export const metadata: Metadata = {
  title: { default: "moloko", template: "%s · moloko" },
  description: "moloko — personal AI office",
  robots: { index: false, follow: false },
  icons: {
    icon: [{ url: "/icons/favicon-32.png", sizes: "32x32", type: "image/png" }],
    apple: [{ url: "/icons/apple-touch-icon.png", sizes: "180x180" }],
  },
  appleWebApp: { capable: true, title: "moloko", statusBarStyle: "default" },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  // Lets the safe-area insets (iPhone home indicator) reach CSS: the tab bar pads itself with them.
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#faf9f7" },
    { media: "(prefers-color-scheme: dark)", color: "#141414" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const nonce = (await headers()).get("x-nonce") ?? undefined; // set by proxy.ts (CSP)
  return (
    <html lang={locale} className={officeFont.variable} suppressHydrationWarning>
      <body className="min-h-dvh">
        {/* The sidebar width the owner chose on this device, applied before the first paint. */}
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: SIDEBAR_INIT_SCRIPT + STYLE_INIT }} suppressHydrationWarning />
        <NextIntlClientProvider>
          <Providers nonce={nonce}>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
