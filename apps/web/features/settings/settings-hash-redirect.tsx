"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { sectionForHash } from "./sections";

/** `/settings#agents` (links and bookmarks from before the sections had pages) opens that page. */
export function SettingsHashRedirect() {
  const router = useRouter();
  useEffect(() => {
    const section = sectionForHash(window.location.hash);
    if (section) router.replace(`/settings/${section}`);
  }, [router]);
  return null;
}
