"use client";

import type { CostSummary, ModelOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronLeft, ChevronRight, OctagonAlert, Save } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { EmptyState } from "@/features/mascot/empty-state";
import { costKeys, getCosts, updateBudget } from "@/lib/api/costs";
import { listAllModels, providerKeys, updateModel } from "@/lib/api/providers";
import { cn } from "@/lib/utils";

import { budgetLevel, fillDays, tokens, usd } from "./format";

function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const d = new Date(Date.UTC(y, m - 1 + by, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

/** Settings → Costs: tokens and approximate money per agent, model and day; the monthly limit. */
export function CostsView() {
  const t = useTranslations("costs");
  const locale = useLocale();
  const format = useFormatter();
  const [month, setMonth] = useState<string | null>(null);
  const costs = useQuery({ queryKey: costKeys.month(month), queryFn: ({ signal }) => getCosts(month, signal) });
  const data = costs.data;
  const current = data?.month ?? null;
  const isThisMonth = month === null;

  if (!data) return <p className="text-sm text-muted-foreground">{t("loading")}</p>;
  const label = format.dateTime(new Date(`${data.month}-01T12:00:00Z`), { month: "long", year: "numeric" });

  return (
    <div className="flex max-w-5xl flex-col gap-4">
      <div className="flex items-center gap-2">
        <Button variant="outline" size="icon" aria-label={t("prevMonth")} onClick={() => setMonth(shiftMonth(current!, -1))}>
          <ChevronLeft />
        </Button>
        <p className="min-w-40 text-center font-pixel text-lg capitalize" aria-live="polite">
          {label}
        </p>
        <Button
          variant="outline"
          size="icon"
          aria-label={t("nextMonth")}
          disabled={isThisMonth}
          onClick={() => {
            const next = shiftMonth(current!, 1);
            setMonth(next === shiftMonth(new Date().toISOString().slice(0, 7), 0) ? null : next);
          }}
        >
          <ChevronRight />
        </Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <SpentTile data={data} locale={locale} isThisMonth={isThisMonth} />
        <Tile title={t("tokens")} value={tokens(data.input_tokens + data.output_tokens, locale)}>
          {t("tokensSplit", { input: tokens(data.input_tokens, locale), output: tokens(data.output_tokens, locale) })}
        </Tile>
        <Tile title={t("calls")} value={format.number(data.calls)}>
          {data.unpriced_calls > 0 ? t("unpriced", { count: data.unpriced_calls }) : t("allPriced")}
        </Tile>
      </div>

      <DailyChart data={data} locale={locale} />

      {data.calls === 0 ? (
        <EmptyState title={t("empty")} hint={t("emptyHint")} mood="sleep" className="rounded-lg border border-dashed" />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <BreakdownTable
            title={t("byAgent")}
            rows={data.by_agent.map((r) => ({
              key: `${r.agent_id ?? r.source}-${r.name}`,
              name: r.source === "chat" ? t("chat") : r.name,
              hint: r.source === "orchestrator" ? t("orchestrator") : undefined,
              calls: r.calls,
              tokens: r.input_tokens + r.output_tokens,
              cost: r.cost_usd,
            }))}
            locale={locale}
          />
          <BreakdownTable
            title={t("byModel")}
            rows={data.by_model.map((r) => ({
              key: `${r.provider_kind}-${r.model}`,
              name: r.model,
              hint: r.unpriced_calls ? t("noPrice") : (r.provider_kind ?? undefined),
              calls: r.calls,
              tokens: r.input_tokens + r.output_tokens,
              cost: r.cost_usd,
            }))}
            locale={locale}
          />
        </div>
      )}

      <BudgetCard data={data} />
      <PricesCard />
    </div>
  );
}

function Tile({ title, value, children }: { title: string; value: string; children?: ReactNode }) {
  return (
    <Card>
      <CardHeader className="pb-1">
        <CardDescription>{title}</CardDescription>
        <CardTitle className="text-3xl tabular-nums">{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-xs text-muted-foreground">{children}</CardContent>
    </Card>
  );
}

function SpentTile({ data, locale, isThisMonth }: { data: CostSummary; locale: string; isThisMonth: boolean }) {
  const t = useTranslations("costs");
  const { budget } = data;
  const level = isThisMonth ? budgetLevel(budget.percent, budget.warn_percent) : "none";
  const width = Math.min(100, budget.percent ?? 0);
  return (
    <Card data-testid="costs-spent">
      <CardHeader className="pb-1">
        <CardDescription>{t("spent")}</CardDescription>
        <CardTitle className="text-3xl tabular-nums">{usd(data.spent_usd, locale)}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-xs text-muted-foreground">
        {budget.monthly_limit_usd !== null && isThisMonth ? (
          <>
            <div
              role="meter"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(budget.percent ?? 0)}
              aria-label={t("ofLimit", { percent: Math.round(budget.percent ?? 0) })}
              className="h-2 overflow-hidden rounded-full bg-muted"
            >
              <div
                className={cn(
                  "h-full rounded-full",
                  level === "over" ? "bg-destructive" : level === "warning" ? "bg-amber-500" : "bg-[var(--chart-bar)]",
                )}
                style={{ width: `${width}%` }}
              />
            </div>
            <p className="flex items-center gap-1">
              {level === "over" && <OctagonAlert className="size-3.5 text-destructive" aria-hidden="true" />}
              {level === "warning" && <AlertTriangle className="size-3.5 text-amber-600" aria-hidden="true" />}
              <span>
                {level === "over" ? t("over") : level === "warning" ? t("near") : null}{" "}
                {t("limitLine", {
                  percent: Math.round(budget.percent ?? 0),
                  limit: usd(budget.monthly_limit_usd, locale),
                })}
              </span>
            </p>
          </>
        ) : (
          <p>{isThisMonth ? t("noLimit") : t("pastMonth")}</p>
        )}
      </CardContent>
    </Card>
  );
}

/** One series (cost per day): single hue, thin rounded bars on a baseline, hover tooltip. */
function DailyChart({ data, locale }: { data: CostSummary; locale: string }) {
  const t = useTranslations("costs");
  const format = useFormatter();
  const days = fillDays(data.month, data.by_day);
  const tokensByDay = new Map(data.by_day.map((d) => [d.day, d.tokens]));
  const max = Math.max(...days.map((d) => d.cost), 0);
  const [hover, setHover] = useState<number | null>(null);
  const W = 640;
  const H = 160;
  const pad = { top: 12, bottom: 20, left: 4, right: 4 };
  const slot = (W - pad.left - pad.right) / days.length;
  const barW = Math.max(3, Math.min(14, slot - 2));
  const plotH = H - pad.top - pad.bottom;
  const shown = hover !== null ? days[hover] : null;
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{t("perDay")}</CardTitle>
        <CardDescription>{max > 0 ? t("perDayMax", { max: usd(max, locale) }) : t("perDayEmpty")}</CardDescription>
      </CardHeader>
      <CardContent className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className="h-40 w-full" role="img" aria-label={t("perDay")} onMouseLeave={() => setHover(null)}>
          <line x1={pad.left} x2={W - pad.right} y1={H - pad.bottom} y2={H - pad.bottom} className="stroke-border" strokeWidth={1} />
          {days.map((d, i) => {
            const h = max > 0 ? Math.max(d.cost > 0 ? 2 : 0, (d.cost / max) * plotH) : 0;
            const x = pad.left + i * slot + (slot - barW) / 2;
            const y = H - pad.bottom - h;
            const r = Math.min(4, barW / 2, h);
            return (
              <g key={d.day} onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)}>
                {/* hit target: the whole column */}
                <rect x={pad.left + i * slot} y={pad.top} width={slot} height={plotH} fill="transparent" />
                {h > 0 && (
                  <path
                    d={`M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + barW - r} Q${x + barW},${y} ${x + barW},${y + r} V${y + h} Z`}
                    className={cn("fill-[var(--chart-bar)]", hover !== null && hover !== i && "opacity-60")}
                  />
                )}
                {(i === 0 || (i + 1) % 10 === 0 || i === days.length - 1) && (
                  <text x={pad.left + i * slot + slot / 2} y={H - 6} textAnchor="middle" className="fill-muted-foreground text-[10px]">
                    {i + 1}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
        {shown && (
          <div
            role="tooltip"
            className="pointer-events-none absolute top-0 rounded-md border bg-card px-2 py-1 text-xs shadow"
            style={{ left: `clamp(0px, calc(${((hover! + 0.5) / days.length) * 100}% - 4rem), calc(100% - 8rem))` }}
          >
            <p className="font-medium">{format.dateTime(new Date(`${shown.day}T12:00:00Z`), { day: "numeric", month: "long" })}</p>
            <p className="tabular-nums">
              {usd(shown.cost, locale)} · {tokens(tokensByDay.get(shown.day) ?? 0, locale)} {t("tokensShort")}
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function BreakdownTable({
  title,
  rows,
  locale,
}: {
  title: string;
  rows: { key: string; name: string; hint?: string; calls: number; tokens: number; cost: string }[];
  locale: string;
}) {
  const t = useTranslations("costs");
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-muted-foreground">
            <tr>
              <th className="py-1 font-normal">{t("colName")}</th>
              <th className="py-1 text-right font-normal">{t("colCalls")}</th>
              <th className="py-1 text-right font-normal">{t("colTokens")}</th>
              <th className="py-1 text-right font-normal">{t("colCost")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-t">
                <td className="py-1.5">
                  <span className="block max-w-56 truncate">{r.name}</span>
                  {r.hint && <span className="text-xs text-muted-foreground">{r.hint}</span>}
                </td>
                <td className="py-1.5 text-right tabular-nums">{r.calls}</td>
                <td className="py-1.5 text-right tabular-nums">{tokens(r.tokens, locale)}</td>
                <td className="py-1.5 text-right tabular-nums">{usd(r.cost, locale)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function BudgetCard({ data }: { data: CostSummary }) {
  const t = useTranslations("costs.budget");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [limit, setLimit] = useState(data.budget.monthly_limit_usd ?? "");
  const [warn, setWarn] = useState(String(data.budget.warn_percent));
  const [hardStop, setHardStop] = useState(data.budget.hard_stop);
  const save = useMutation({
    mutationFn: () =>
      updateBudget({
        monthly_limit_usd: limit.trim() === "" ? null : limit.trim().replace(",", "."),
        warn_percent: Number(warn) || 80,
        hard_stop: hardStop,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: costKeys.all }),
  });
  return (
    <Card data-testid="budget-settings">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="budget-limit">{t("limit")}</Label>
              <Input id="budget-limit" inputMode="decimal" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder={t("limitPlaceholder")} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="budget-warn">{t("warn")}</Label>
              <Input id="budget-warn" type="number" min={10} max={99} value={warn} onChange={(e) => setWarn(e.target.value)} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4" checked={hardStop} onChange={(e) => setHardStop(e.target.checked)} />
            {t("hardStop")}
          </label>
          {save.error && (
            <p role="alert" className="text-sm text-destructive">
              {toMessage(save.error).message}
            </p>
          )}
          {save.isSuccess && <p className="text-sm text-muted-foreground">{t("saved")}</p>}
          <Button type="submit" className="self-start" disabled={save.isPending}>
            <Save /> {t("save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function PricesCard() {
  const t = useTranslations("costs.prices");
  const models = useQuery({ queryKey: providerKeys.models, queryFn: ({ signal }) => listAllModels(signal) });
  const rows = (models.data ?? []).filter((m: ModelOut) => m.enabled);
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {rows.length === 0 && <p className="text-sm text-muted-foreground">{t("none")}</p>}
        {rows.map((m) => (
          <PriceRow key={m.id} model={m} />
        ))}
      </CardContent>
    </Card>
  );
}

function PriceRow({ model }: { model: ModelOut }) {
  const t = useTranslations("costs.prices");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [input, setInput] = useState(model.input_price_per_mtok ?? "");
  const [output, setOutput] = useState(model.output_price_per_mtok ?? "");
  const save = useMutation({
    mutationFn: () =>
      updateModel(model.id, {
        input_price_per_mtok: input.trim() === "" ? null : input.trim().replace(",", "."),
        output_price_per_mtok: output.trim() === "" ? null : output.trim().replace(",", "."),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: providerKeys.models });
      void queryClient.invalidateQueries({ queryKey: costKeys.all });
    },
  });
  return (
    <form
      className="grid items-end gap-2 border-t pt-2 sm:grid-cols-[1fr_8rem_8rem_auto]"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate();
      }}
    >
      <p className="truncate text-sm">
        {model.display_name || model.model}
        <span className="block text-xs text-muted-foreground">{model.provider_name}</span>
      </p>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`in-${model.id}`} className="text-xs">
          {t("input")}
        </Label>
        <Input id={`in-${model.id}`} inputMode="decimal" value={input} onChange={(e) => setInput(e.target.value)} placeholder="—" />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`out-${model.id}`} className="text-xs">
          {t("output")}
        </Label>
        <Input id={`out-${model.id}`} inputMode="decimal" value={output} onChange={(e) => setOutput(e.target.value)} placeholder="—" />
      </div>
      <Button type="submit" variant="outline" size="sm" disabled={save.isPending}>
        {save.isSuccess ? t("saved") : t("save")}
      </Button>
      {save.error && (
        <p role="alert" className="text-xs text-destructive sm:col-span-4">
          {toMessage(save.error).message}
        </p>
      )}
    </form>
  );
}
