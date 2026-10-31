"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { LocaleSwitcher } from "@/features/preferences/locale-switcher";
import { ThemeToggle } from "@/features/preferences/theme-toggle";
import { authKeys, getMe, logout } from "@/lib/api/auth";
import { ApiError } from "@/lib/api/errors";
import { cn } from "@/lib/utils";

import { NAV_ITEMS } from "./nav-items";

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: ReactNode }) {
  const t = useTranslations();
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const toMessage = useErrorMessage();

  // The backend decides whether we are signed in; the UI only reflects it.
  const me = useQuery({ queryKey: authKeys.me, queryFn: ({ signal }) => getMe(signal) });

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.isUnauthenticated) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [me.error, pathname, router]);

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.clear();
      router.replace("/login");
    },
  });

  if (me.isPending || (me.error instanceof ApiError && me.error.isUnauthenticated)) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-sm text-muted-foreground">
        {t("common.loading")}
      </div>
    );
  }

  if (me.isError) {
    const { message, errorId } = toMessage(me.error);
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 px-4 text-center">
        <p role="alert">{message}</p>
        {errorId && <p className="font-mono text-xs text-muted-foreground">{errorId}</p>}
        <Button variant="outline" onClick={() => me.refetch()}>
          {t("common.retry")}
        </Button>
      </div>
    );
  }

  const user = me.data.user;
  const displayName = user.display_name || user.username;

  return (
    <div className="flex min-h-dvh">
      {/* Desktop / tablet sidebar */}
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r bg-card md:flex">
        <div className="flex h-16 items-center px-4">
          <Link href="/chat" aria-label="moloko">
            <Logo />
          </Link>
        </div>
        <nav aria-label={t("nav.label")} className="flex flex-1 flex-col gap-1 px-2 py-2">
          {NAV_ITEMS.map(({ href, labelKey, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-current={isActive(pathname, href) ? "page" : undefined}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive(pathname, href)
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/60 hover:text-foreground",
              )}
            >
              <Icon className="size-4" />
              {t(`nav.${labelKey}`)}
            </Link>
          ))}
        </nav>
        <div className="flex flex-col gap-3 border-t p-3">
          <p className="truncate text-xs text-muted-foreground" title={user.username}>
            {t("auth.signedInAs", { name: displayName })}
          </p>
          <div className="flex items-center justify-between gap-2">
            <LocaleSwitcher />
            <div className="flex items-center">
              <ThemeToggle />
              <Button
                variant="ghost"
                size="icon"
                onClick={() => signOut.mutate()}
                disabled={signOut.isPending}
                aria-label={t("auth.logout")}
                title={t("auth.logout")}
              >
                <LogOut />
              </Button>
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {/* Mobile top bar */}
        <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b bg-card/95 px-4 backdrop-blur md:hidden">
          <Link href="/chat" aria-label="moloko">
            <Logo className="[&_svg]:size-7 [&>span:last-child]:text-lg" />
          </Link>
          <div className="flex items-center gap-1">
            <LocaleSwitcher />
            <ThemeToggle />
            <Button
              variant="ghost"
              size="icon"
              onClick={() => signOut.mutate()}
              disabled={signOut.isPending}
              aria-label={t("auth.logout")}
            >
              <LogOut />
            </Button>
          </div>
        </header>

        <main className="flex-1 px-4 pt-6 pb-24 md:px-8 md:pb-8">{children}</main>

        {/* Mobile bottom tab bar */}
        <nav
          aria-label={t("nav.label")}
          className="fixed inset-x-0 bottom-0 z-10 grid grid-cols-6 border-t bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
        >
          {NAV_ITEMS.map(({ href, labelKey, shortLabelKey, icon: Icon }) => (
            <Link
              key={href}
              href={href}
              aria-label={t(`nav.${labelKey}`)}
              aria-current={isActive(pathname, href) ? "page" : undefined}
              className={cn(
                "flex flex-col items-center gap-1 px-1 py-2 text-[10px] leading-tight",
                isActive(pathname, href) ? "text-foreground" : "text-muted-foreground",
              )}
            >
              <Icon className="size-5" />
              <span className="line-clamp-1 text-center" aria-hidden="true">
                {t(`nav.${shortLabelKey ?? labelKey}`)}
              </span>
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );
}
