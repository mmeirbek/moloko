"use client";

import { useTranslations } from "next-intl";
import { useState, useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  DEFAULT_PREFS,
  prefsSnapshot,
  savePrefs,
  subscribePrefs,
  type NotificationPrefs,
} from "@/lib/notifications/rules";

const noop = () => () => {};
const permissionNow = () => (typeof Notification === "undefined" ? "unsupported" : Notification.permission);

export function NotificationsSection() {
  const t = useTranslations("notifications.settings");
  const prefs = useSyncExternalStore(subscribePrefs, prefsSnapshot, () => DEFAULT_PREFS);
  const browserPermission = useSyncExternalStore(noop, permissionNow, () => "default");
  const [asked, setAsked] = useState<string | null>(null);
  const permission = asked ?? browserPermission;
  const update = (next: NotificationPrefs) => savePrefs(next);
  async function allowSystem() {
    if (typeof Notification === "undefined") return;
    const result = await Notification.requestPermission();
    setAsked(result);
    update({ ...prefs, system: result === "granted" });
  }
  return (
    <Card id="notifications">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {(["approval", "taskDone", "taskFailed"] as const).map((kind) => (
          <label key={kind} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={prefs[kind]}
              onChange={(e) => update({ ...prefs, [kind]: e.target.checked })}
            />
            {t(`kinds.${kind}`)}
          </label>
        ))}
        <div className="flex flex-wrap items-center gap-2 border-t pt-3">
          {permission === "granted" ? (
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={prefs.system}
                onChange={(e) => update({ ...prefs, system: e.target.checked })}
              />
              {t("system")}
            </label>
          ) : permission === "unsupported" ? (
            <p className="text-muted-foreground">{t("unsupported")}</p>
          ) : (
            <Button variant="outline" size="sm" onClick={() => void allowSystem()} disabled={permission === "denied"}>
              {permission === "denied" ? t("blocked") : t("allow")}
            </Button>
          )}
        </div>
        <p className="text-xs text-muted-foreground">{t("closedNote")}</p>
      </CardContent>
    </Card>
  );
}
