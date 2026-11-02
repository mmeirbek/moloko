"""Notification wording: short, human, in the owner's language — never raw commands, file
contents or long paths (the same rules as ``apps/web/lib/notifications/rules.ts``)."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any
from urllib.parse import urlsplit

TITLE_MAX = 90

# What an agent asks to do, by tool. {file} is a file name (not the whole path), {program}
# the command's program (python3, npm, git…), never the command itself.
OPS: dict[str, dict[str, str]] = {
    "ru": {
        "fs_write": "Записать файл {file}",
        "fs_append": "Дописать файл {file}",
        "fs_move": "Переместить файл {file}",
        "fs_delete": "Удалить файл {file}",
        "terminal_run": "Выполнить команду {program}",
        "terminal_run_plain": "Выполнить команду",
        "github_create_branch": "Создать ветку {branch} в {repo}",
        "github_write_file": "Сохранить файл {file} в GitHub ({repo})",
        "github_create_pull_request": "Открыть pull request в {repo}",
        "memory_save": "Сохранить в память: {title}",
        "browser_screenshot": "Открыть страницу {host}",
        "agent_ask": "Спросить агента {agent}",
        "agent_tell": "Написать агенту {agent}",
        "other": "Действие: {tool}",
    },
    "en": {
        "fs_write": "Write the file {file}",
        "fs_append": "Append to the file {file}",
        "fs_move": "Move the file {file}",
        "fs_delete": "Delete the file {file}",
        "terminal_run": "Run a {program} command",
        "terminal_run_plain": "Run a command",
        "github_create_branch": "Create the branch {branch} in {repo}",
        "github_write_file": "Save {file} to GitHub ({repo})",
        "github_create_pull_request": "Open a pull request in {repo}",
        "memory_save": "Save to memory: {title}",
        "browser_screenshot": "Open the page {host}",
        "agent_ask": "Ask the agent {agent}",
        "agent_tell": "Message the agent {agent}",
        "other": "Action: {tool}",
    },
}

# Why a task stopped (the same codes as the web app's ``tasks.errors``).
REASONS: dict[str, dict[str, str]] = {
    "ru": {
        "empty_result": "агент закончил без результата",
        "output_truncated": "ответы модели не помещались в лимит",
        "max_steps_exceeded": "закончились шаги",
        "run_timeout": "вышло время",
        "subtasks_failed": "не удались части задачи",
        "invalid_plan": "не получилось составить план",
        "budget_exceeded": "достигнут месячный лимит расходов",
        "agent_budget_exceeded": "агент израсходовал свой бюджет",
        "interrupted": "сервер перезапускался",
        "internal_error": "внутренняя ошибка",
    },
    "en": {
        "empty_result": "the agent finished without a result",
        "output_truncated": "the model's replies did not fit the limit",
        "max_steps_exceeded": "out of steps",
        "run_timeout": "out of time",
        "subtasks_failed": "parts of the task failed",
        "invalid_plan": "no workable plan",
        "budget_exceeded": "the monthly cost limit was reached",
        "agent_budget_exceeded": "the agent used up its budget",
        "interrupted": "the server restarted",
        "internal_error": "an internal error",
    },
}

_MARKERS = re.compile(r"\[\[[^\]]*\]\]")  # [[mock:…]] and similar machine markers
_FENCES = re.compile(r"```.*?(```|$)", re.S)


def lang(locale: str) -> str:
    return "en" if locale.startswith("en") else "ru"


def short_text(text: str, limit: int = TITLE_MAX) -> str:
    """One readable line: no code blocks or markers, whitespace collapsed, cut at a word."""
    text = _FENCES.sub(" ", text or "")
    text = _MARKERS.sub(" ", text)
    text = text.replace("`", "").replace("#", " ")
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut[limit // 2 :]:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,.;:—-") + "…"


def _file(path: Any) -> str:
    name = PurePosixPath(str(path or "").strip()).name
    return short_text(name, 50) or "?"


def _program(command: Any) -> str:
    first = str(command or "").strip().split(maxsplit=1)
    if not first:
        return ""
    word = PurePosixPath(first[0]).name
    return word if re.fullmatch(r"[A-Za-z0-9_.+-]{1,24}", word) else ""


def approval_text(locale: str, tool_name: str, args: dict[str, Any] | None) -> str:
    """«Записать файл layout.tsx» — what the agent wants to do, without code or contents."""
    ops = OPS[lang(locale)]
    a = args or {}
    if tool_name in ("fs_write", "fs_append", "fs_delete"):
        if tool_name == "fs_write" and a.get("mode") == "append":
            tool_name = "fs_append"
        return ops[tool_name].format(file=_file(a.get("path")))
    if tool_name == "fs_move":
        return ops["fs_move"].format(file=_file(a.get("source")))
    if tool_name == "terminal_run":
        program = _program(a.get("command"))
        return ops["terminal_run"].format(program=program) if program else ops["terminal_run_plain"]
    if tool_name == "github_create_branch":
        return ops[tool_name].format(
            branch=short_text(str(a.get("branch", "")), 40),
            repo=short_text(str(a.get("repo", "")), 60),
        )
    if tool_name == "github_write_file":
        return ops[tool_name].format(
            file=_file(a.get("path")), repo=short_text(str(a.get("repo", "")), 60)
        )
    if tool_name == "github_create_pull_request":
        return ops[tool_name].format(repo=short_text(str(a.get("repo", "")), 60))
    if tool_name == "memory_save":
        return ops[tool_name].format(title=short_text(str(a.get("title", "")), 60))
    if tool_name == "browser_screenshot":
        host = urlsplit(str(a.get("url", ""))).hostname or short_text(str(a.get("url", "")), 40)
        return ops[tool_name].format(host=host)
    if tool_name in ("agent_ask", "agent_tell"):
        return ops[tool_name].format(agent=short_text(str(a.get("agent", "")), 40))
    return ops["other"].format(tool=short_text(tool_name.replace("_", " "), 40))


def failure_reason(locale: str, error_code: str | None) -> str:
    return REASONS[lang(locale)].get(error_code or "", "")
