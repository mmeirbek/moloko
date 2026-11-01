import type { Metadata, Viewport } from "next";
import { NextIntlClientProvider } from "next-intl";
import { getLocale } from "next-intl/server";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { Providers } from "./providers";
import "./globals.css";

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
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbf8ef" },
    { media: "(prefers-color-scheme: dark)", color: "#0c1024" },
  ],
};

export default async function RootLayout({ children }: { children: ReactNode }) {
  const locale = await getLocale();
  const nonce = (await headers()).get("x-nonce") ?? undefined; // set by proxy.ts (CSP)
  return (
    <html lang={locale} suppressHydrationWarning>
      <body className="min-h-dvh">
        <NextIntlClientProvider>
          <Providers nonce={nonce}>{children}</Providers>
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
