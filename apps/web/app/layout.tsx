import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import localFont from "next/font/local";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { SIDEBAR_INIT_SCRIPT } from "@/components/layout/sidebar-prefs";

import { Providers } from "./providers";
import "./globals.css";

// Moloko Pixel — our own pixel font, drawn after the "moloko" lettering of the logo
// (bitmaps: assets/brand/moloko-pixel.txt, built by scripts/make-font.py). Latin + Russian.
// One weight: headings never get a fake bold.
const headingFont = localFont({
  src: "./fonts/MolokoPixel.woff2",
  variable: "--font-heading",
  weight: "400",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});

// Ark Pixel 12px by TakWolf — SIL Open Font License 1.1 (app/fonts/ArkPixel-OFL.txt), self-hosted,
// subset to Latin + Cyrillic + punctuation by scripts/subset-ark.py. Text and code.
const bodyFont = localFont({
  src: "./fonts/ArkPixel12.woff2",
  variable: "--font-body",
  weight: "400",
  display: "swap",
  fallback: ["ui-sans-serif", "system-ui", "sans-serif"],
});
const codeFont = localFont({
  src: "./fonts/ArkPixel12Mono.woff2",
  variable: "--font-code",
  weight: "400",
  display: "swap",
  fallback: ["ui-monospace", "monospace"],
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
    { media: "(prefers-color-scheme: light)", color: "#fbf8ef" },
    { media: "(prefers-color-scheme: dark)", color: "#0c1024" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const nonce = (await headers()).get("x-nonce") ?? undefined; // set by proxy.ts (CSP)
  return (
    <html lang={locale} className={`${headingFont.variable} ${bodyFont.variable} ${codeFont.variable}`} suppressHydrationWarning>
      <body className="min-h-dvh">
        {/* The sidebar width the owner chose on this device, applied before the first paint. */}
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: SIDEBAR_INIT_SCRIPT }} suppressHydrationWarning />
        <NextIntlClientProvider>
          <Providers nonce={nonce}>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
