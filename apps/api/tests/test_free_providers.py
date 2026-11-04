"""Free tiers of official APIs (presets taken from freellmapi's list) and the Orchestrator
picking the best model for each part from what every model family is best at."""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.models import Task, User
from app.orchestrator.plan import parse_plan
from app.orchestrator.prompts import planning_system
from app.providers import mock_provider
from app.providers.base import ChatRequest, ChatResult, ModelInfo
from app.providers.free_catalog import BY_KEY, FREE_PROVIDERS, free_models, preset_for
from app.providers.model_profiles import describe, profile_for
from tests.conftest import RecordingQueue, add_mock_model, csrf_headers, drain, logged_in_client


def ids(models: list[ModelInfo]) -> list[str]:
    return [m.id for m in models]


def test_presets_are_official_https_apis_with_a_key_page() -> None:
    assert {"google", "groq", "cerebras", "mistral", "openrouter", "github"} <= set(BY_KEY)
    assert "cohere" not in BY_KEY  # its terms forbid personal use
    for p in FREE_PROVIDERS:
        assert p.base_url.startswith("https://") and p.key_url.startswith("https://")
        assert preset_for(p.base_url.replace("{account_id}", "abc")) is p
    assert preset_for("https://api.openai.com/v1") is None
    assert preset_for(None) is None


def test_only_free_chat_models_are_imported() -> None:
    listed = [ModelInfo(i) for i in ("deepseek/deepseek-v3.1:free", "openai/gpt-5", "x/embed:free")]
    assert ids(free_models("https://openrouter.ai/api/v1", listed)) == [
        "deepseek/deepseek-v3.1:free"
    ]
    gemini = [ModelInfo(i) for i in ("models/gemini-2.5-pro", "models/text-embedding-004")]
    assert ids(free_models("https://generativelanguage.googleapis.com/v1beta/openai", gemini)) == [
        "gemini-2.5-pro"
    ]
    groq = [ModelInfo(i) for i in ("llama-3.3-70b-versatile", "whisper-large-v3")]
    assert ids(free_models("https://api.groq.com/openai/v1", groq)) == ["llama-3.3-70b-versatile"]
    # a platform that lists nothing: its known models
    assert "openai/gpt-5" in ids(free_models("https://models.github.ai/inference", []))
    # not a free platform: untouched
    assert ids(free_models("https://api.openai.com/v1", listed)) == ids(listed)


def test_every_family_knows_what_it_is_best_at() -> None:
    assert "code" in profile_for("qwen-3-coder-480b").best_at
    assert "reasoning" in profile_for("deepseek/deepseek-r1:free").best_at
    assert "long_context" in profile_for("gemini-2.5-pro").best_at
    assert profile_for("gpt-5-mini").family == "GPT-5 mini"  # specific before general
    assert profile_for("gemini-2.5-flash-lite").family == "Gemini Flash-Lite"
    assert profile_for("some-unknown-model").best_at == ()
    line = describe("qwen-3-coder-480b @ Cerebras", "qwen-3-coder-480b")
    assert line.startswith("qwen-3-coder-480b @ Cerebras — strongest") and "best at: code" in line


def test_a_plan_names_models_from_the_owners_list_only() -> None:
    models = {"qwen-3-coder-480b @ Cerebras": "m-code", "gemini-2.5-pro @ Google Gemini": "m-long"}
    text = json.dumps(
        {
            "mode": "delegate",
            "new_agents": [{"name": "Reader", "model": "gemini-2.5-pro"}],
            "subtasks": [
                {
                    "key": "a",
                    "title": "Code",
                    "agent": "W",
                    "model": "qwen-3-coder-480b @ Cerebras",
                },
                {"key": "b", "title": "Read", "agent": "Reader", "model": "gpt-9-ultra"},
                {"key": "c", "title": "Other", "agent": "W"},
            ],
        }
    )
    plan, warnings = parse_plan(text, max_subtasks=8, agents=["W"], max_new_agents=1, models=models)
    assert [s.model for s in plan.subtasks] == ["m-code", "", ""]
    assert plan.new_agents[0].model == "m-long"  # the short name is enough when unambiguous
    assert any("gpt-9-ultra" in w for w in warnings)
    prompt = planning_system(max_subtasks=8, max_active=3, max_new_agents=1, models=("x — y",))
    assert "- x — y" in prompt and '"model"' in prompt and "senior lead" in prompt
    assert "Models you can give" not in planning_system(
        max_subtasks=8, max_active=3, max_new_agents=1
    )


async def test_the_part_runs_on_the_model_the_orchestrator_picked(
    app: FastAPI, owner: User, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.orchestrator.prompts import PROTOCOL_PLAN

    used: list[str] = []

    def model(req: ChatRequest) -> ChatResult | None:
        if PROTOCOL_PLAN in (req.system or ""):
            assert "Models you can give a part" in (req.system or "")
            lines = (req.system or "").splitlines()
            line = next(x for x in lines if x.startswith("- mock-smart"))
            name = line[2:].split(" — ")[0]
            plan = {
                "mode": "delegate",
                "new_agents": [{"name": "Coder"}],
                "subtasks": [{"key": "a", "title": "Do it", "agent": "Coder", "model": name}],
            }
            return ChatResult(text=json.dumps(plan))
        used.append(req.model)
        return ChatResult(text="Done.")

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(app) as client:
        await add_mock_model(client)  # the default is mock-fast
        resp = await client.post(
            "/api/v1/runs", json={"title": "Build"}, headers=await csrf_headers(client)
        )
        assert resp.status_code == 200, resp.text
        await drain(app, queue)
    async with app.state.db.sessionmaker() as db:
        part = (await db.execute(select(Task).where(Task.parent_task_id.is_not(None)))).scalar_one()
    assert part.status == "completed"
    picked = part.extra["model_config_id"]
    assert uuid.UUID(picked)
    # the part on the picked model (not the default); the merge on the Orchestrator's own
    assert used == ["mock-smart", "mock-fast"]


def test_only_chat_models_are_offered_for_parts() -> None:
    from app.providers.model_profiles import chat_capable

    for model in ("gpt-5-search-api", "text-embedding-3-large", "gpt-4o-mini-tts", "dall-e-3"):
        assert not chat_capable(model)
    assert chat_capable("gpt-5.1") and chat_capable("gemini-2.5-pro")
    # Responses-only on OpenAI itself, fine elsewhere (e.g. OpenRouter)
    assert not chat_capable("gpt-5.2-codex", openai_direct=True)
    assert not chat_capable("gpt-5-pro", openai_direct=True)
    assert chat_capable("openai/gpt-5-codex")


async def test_a_part_whose_picked_model_refuses_goes_on_with_its_agents_model(
    app: FastAPI, owner: User, queue: RecordingQueue, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner's failure of 2026-11-04: the Orchestrator picked models the provider refused
    («model not found»), so every part failed and the whole task with them."""
    from app.models.provider import ModelConfig
    from app.orchestrator.prompts import PROTOCOL_PLAN
    from app.providers.base import ProviderError

    used: list[str] = []

    def model(req: ChatRequest) -> ChatResult | None:
        if PROTOCOL_PLAN in (req.system or ""):
            plan = {
                "mode": "delegate",
                "new_agents": [{"name": "Coder"}],
                "subtasks": [
                    {"key": "a", "title": "Do it", "agent": "Coder", "model": "mock-smart"}
                ],
            }
            return ChatResult(text=json.dumps(plan))
        used.append(req.model)
        if req.model == "mock-smart":
            raise ProviderError("model_not_found", provider="mock")
        return ChatResult(text="Done.")

    monkeypatch.setattr(mock_provider, "_handlers", [model])
    async with logged_in_client(app) as client:
        await add_mock_model(client)  # the default (and the new agent's model) is mock-fast
        resp = await client.post(
            "/api/v1/runs", json={"title": "Build"}, headers=await csrf_headers(client)
        )
        assert resp.status_code == 200, resp.text
        await drain(app, queue)
    async with app.state.db.sessionmaker() as db:
        parent = (await db.execute(select(Task).where(Task.parent_task_id.is_(None)))).scalar_one()
        part = (await db.execute(select(Task).where(Task.parent_task_id.is_not(None)))).scalar_one()
        smart = (
            await db.execute(select(ModelConfig).where(ModelConfig.model == "mock-smart"))
        ).scalar_one()
    assert part.status == "completed" and parent.status == "completed"
    assert used[:2] == ["mock-smart", "mock-fast"]  # refused, then the agent's own model
    assert "model_config_id" not in part.extra
    assert smart.params.get("not_for_plans") == "model_not_found"  # not offered again
