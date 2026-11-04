"""Free tiers of the official APIs (owner, 2026-11-03: use all the models of freellmapi, make it
part of our project). The list of platforms, their OpenAI-compatible addresses
and their terms come from tashfeenahmed/freellmapi (MIT, read as a reference — no code copied;
THIRD_PARTY_NOTICES.md). Each preset is an ordinary ``openai`` provider with the platform's
address and the owner's own key from that platform (spec 13.5: official API keys only).

Not included (docs/decisions.md): Cohere (its terms forbid personal use) and the small resale
gateways freellmapi also lists — unknown companies would get the owner's prompts and memory.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.providers.base import ModelInfo


@dataclass(frozen=True)
class FreeProvider:
    key: str
    name: str
    base_url: str
    # where the owner gets the key (opens in a new tab); the web app describes each platform
    # (its free allowance, any caution about its terms) in the owner's language
    key_url: str
    # only these model ids are imported (None = every chat model the platform lists)
    models: re.Pattern[str] | None = None
    # model ids to add when the platform does not list its models
    known_models: tuple[str, ...] = field(default_factory=tuple)
    # the address needs the owner's account id in place of {account_id}
    needs_account: bool = False


FREE_PROVIDERS: tuple[FreeProvider, ...] = (
    FreeProvider(
        "google",
        "Google Gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        "https://aistudio.google.com/apikey",
        models=re.compile(r"^(models/)?gemini-"),
    ),
    FreeProvider(
        "groq",
        "Groq",
        "https://api.groq.com/openai/v1",
        "https://console.groq.com/keys",
    ),
    FreeProvider(
        "cerebras",
        "Cerebras",
        "https://api.cerebras.ai/v1",
        "https://cloud.cerebras.ai",
    ),
    FreeProvider(
        "mistral",
        "Mistral",
        "https://api.mistral.ai/v1",
        "https://console.mistral.ai/api-keys",
    ),
    FreeProvider(
        "openrouter",
        "OpenRouter (free models)",
        "https://openrouter.ai/api/v1",
        "https://openrouter.ai/keys",
        models=re.compile(r":free$"),
    ),
    FreeProvider(
        "github",
        "GitHub Models",
        "https://models.github.ai/inference",
        "https://github.com/settings/personal-access-tokens",
        known_models=(
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "openai/gpt-4.1",
            "openai/gpt-4.1-mini",
            "deepseek/deepseek-r1",
            "meta/llama-4-maverick-17b-128e-instruct-fp8",
        ),
    ),
    FreeProvider(
        "nvidia",
        "NVIDIA NIM",
        "https://integrate.api.nvidia.com/v1",
        "https://build.nvidia.com/settings/api-keys",
    ),
    FreeProvider(
        "huggingface",
        "Hugging Face",
        "https://router.huggingface.co/v1",
        "https://huggingface.co/settings/tokens",
    ),
    FreeProvider(
        "sambanova",
        "SambaNova",
        "https://api.sambanova.ai/v1",
        "https://cloud.sambanova.ai/apis",
    ),
    FreeProvider(
        "zhipu",
        "Zhipu GLM",
        "https://open.bigmodel.cn/api/paas/v4",
        "https://open.bigmodel.cn/usercenter/apikeys",
        models=re.compile(r"flash", re.IGNORECASE),
        known_models=("glm-4.5-flash", "glm-4-flash"),
    ),
    FreeProvider(
        "ollama",
        "Ollama Cloud",
        "https://ollama.com/v1",
        "https://ollama.com/settings/keys",
    ),
    FreeProvider(
        "cloudflare",
        "Cloudflare Workers AI",
        "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "https://dash.cloudflare.com/profile/api-tokens",
        known_models=("@cf/meta/llama-3.3-70b-instruct-fp8-fast", "@cf/qwen/qwq-32b"),
        needs_account=True,
    ),
)

BY_KEY = {p.key: p for p in FREE_PROVIDERS}

# Not chat models: never imported from a free platform's list.
_NOT_CHAT = re.compile(
    r"(embed|whisper|tts|speech|audio|transcri|image|vision-only|moderation|rerank|guard|dall-e|"
    r"flux|stable-diffusion|sdxl|clip|ocr|bge|e5-|nomic|-tts|veo|imagen|lyria|aqa)",
    re.IGNORECASE,
)


def preset_for(base_url: str | None) -> FreeProvider | None:
    """The free platform a provider's address belongs to (presets are matched by address)."""
    if not base_url:
        return None
    url = base_url.rstrip("/")
    for p in FREE_PROVIDERS:
        prefix = p.base_url.rstrip("/").split("{account_id}")[0]
        if url.startswith(prefix):
            return p
    return None


def keep_model(preset: FreeProvider, model_id: str) -> bool:
    """Whether a listed model is one of the platform's free chat models."""
    if _NOT_CHAT.search(model_id):
        return False
    return preset.models is None or bool(preset.models.search(model_id))


def free_models(base_url: str | None, listed: list[ModelInfo]) -> list[ModelInfo]:
    """For a free platform: only its free chat models, ids as its chat API takes them
    (Gemini lists ``models/gemini-…``), or its known models when it lists none."""
    preset = preset_for(base_url)
    if preset is None:
        return listed
    seen: dict[str, ModelInfo] = {}
    for info in listed:
        model_id = info.id.removeprefix("models/")
        if keep_model(preset, model_id):
            seen.setdefault(model_id, ModelInfo(id=model_id, display_name=info.display_name))
    if not seen:
        for model_id in preset.known_models:
            seen[model_id] = ModelInfo(id=model_id)
    return sorted(seen.values(), key=lambda m: m.id)
