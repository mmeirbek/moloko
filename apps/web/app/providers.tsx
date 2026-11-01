"use client";

import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useTimeZone } from "next-intl";
import { ThemeProvider } from "next-themes";
import { useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import { TIMEZONE_COOKIE } from "@/i18n/config";
import { ApiError } from "@/lib/api/errors";

/**
 * Tells the server the browser's time zone (a cookie read by i18n/request.ts) and re-renders
 * once if it differs, so every date shows the owner's local time — on the first visit and
 * after travelling.
 */
function TimeZoneSync() {
  const router = useRouter();
  const configured = useTimeZone();
  useEffect(() => {
    const local = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (!local || local === configured) return;
    // IANA names ("Asia/Almaty", "Etc/GMT+5") are valid cookie values as they are.
    document.cookie = `${TIMEZONE_COOKIE}=${local}; path=/; max-age=31536000; samesite=lax`;
    router.refresh();
  }, [configured, router]);
  return null;
}

function redirectToLogin(error: unknown) {
  if (!(error instanceof ApiError) || !error.isUnauthenticated) return;
  if (typeof window === "undefined" || window.location.pathname === "/login") return;
  const next = window.location.pathname + window.location.search;
  // A full page load on purpose: it drops every cached query of the expired session.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

function makeQueryClient() {
  return new QueryClient({
    // Central place for auth expiry: any 401 sends the user back to the login page.
    queryCache: new QueryCache({ onError: redirectToLogin }),
    mutationCache: new MutationCache({ onError: redirectToLogin }),
    defaultOptions: {
      queries: {
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry: (failureCount, error) =>
          !(error instanceof ApiError && error.status >= 400 && error.status < 500) &&
          failureCount < 2,
      },
      mutations: { retry: false },
    },
  });
}

export function Providers({ children, nonce }: { children: ReactNode; nonce?: string }) {
  const [queryClient] = useState(makeQueryClient);
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange nonce={nonce}>
      <QueryClientProvider client={queryClient}>
        <TimeZoneSync />
        {children}
      </QueryClientProvider>
    </ThemeProvider>
  );
}
