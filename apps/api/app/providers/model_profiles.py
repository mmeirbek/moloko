"""What each model family is best at — what the Orchestrator knows when it picks a model for
a part (owner, 2026-11-03: give the Orchestrator the stats of every model and a few areas where
each is the best). Matched by the model id, so a model from any provider (a free platform, the
owner's OpenAI or Anthropic key) gets its family's profile.

The tiers and speeds follow the ranks in tashfeenahmed/freellmapi's catalog (MIT, reference)
and public benchmarks as of mid-2026 (LMArena, SWE-bench, AIME, long-context tests); the areas
are a judgement from those, not a measurement. First match wins: specific ids before general.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The areas a part of a task can need (the prompt names them in English).
AREAS = (
    "code",  # writing and fixing code
    "agentic",  # many tool calls in a row: files, terminal, browser
    "reasoning",  # hard multi-step thinking, planning, analysis
    "math",
    "russian",  # writing in Russian
    "writing",  # texts, letters, summaries in English and other languages
    "research",  # reading many sources, extracting and comparing facts
    "long_context",  # very long inputs: big files, books, whole repositories
    "vision",  # pictures and screenshots
    "fast",  # quick, cheap, simple parts
)


@dataclass(frozen=True)
class ModelProfile:
    family: str
    tier: int  # 1 = the strongest … 5 = small
    speed: int  # 1 = the fastest … 5 = slow
    best_at: tuple[str, ...]
    context_k: int  # context window, thousands of tokens


def _p(family: str, tier: int, speed: int, best: str, context_k: int) -> ModelProfile:
    return ModelProfile(family, tier, speed, tuple(best.split()), context_k)


_FAMILIES: tuple[tuple[str, ModelProfile], ...] = (
    # OpenAI
    (
        r"gpt-5(\.\d)?-?(pro|codex)",
        _p("GPT-5 Pro/Codex", 1, 5, "code agentic reasoning", 400),
    ),
    (r"gpt-5(\.\d)?-?nano", _p("GPT-5 nano", 4, 1, "fast writing", 400)),
    (r"gpt-5(\.\d)?-?mini", _p("GPT-5 mini", 2, 2, "reasoning code fast", 400)),
    (r"gpt-5", _p("GPT-5", 1, 4, "reasoning code russian", 400)),
    (r"gpt-oss-120b", _p("GPT-OSS 120B", 2, 1, "reasoning math agentic", 131)),
    (r"gpt-oss-20b", _p("GPT-OSS 20B", 3, 1, "fast reasoning", 131)),
    (r"gpt-4\.1-(mini|nano)", _p("GPT-4.1 mini", 3, 2, "fast long_context", 1000)),
    (r"gpt-4\.1", _p("GPT-4.1", 2, 3, "long_context code writing", 1000)),
    (r"gpt-4o-mini", _p("GPT-4o mini", 4, 2, "fast vision", 128)),
    (r"gpt-4o", _p("GPT-4o", 3, 3, "vision writing russian", 128)),
    (
        r"\bo[34](-mini)?\b",
        _p("OpenAI o-series", 2, 4, "reasoning math code", 200),
    ),
    # Anthropic
    (r"claude.*opus", _p("Claude Opus", 1, 5, "code agentic writing", 200)),
    (r"claude.*sonnet", _p("Claude Sonnet", 1, 3, "code agentic russian", 200)),
    (r"claude.*haiku", _p("Claude Haiku", 3, 1, "fast code writing", 200)),
    # Google
    (
        r"gemini-3.*pro",
        _p("Gemini 3 Pro", 1, 4, "reasoning vision long_context", 1000),
    ),
    (
        r"gemini-[\d.]+-pro",
        _p("Gemini Pro", 1, 4, "long_context reasoning vision", 1000),
    ),
    (
        r"gemini-[\d.]+-flash-lite",
        _p("Gemini Flash-Lite", 3, 1, "fast vision long_context", 1000),
    ),
    (
        r"gemini-[\d.]+-flash",
        _p("Gemini Flash", 2, 2, "long_context vision fast", 1000),
    ),
    (r"gemma", _p("Gemma", 4, 2, "fast writing", 128)),
    # DeepSeek
    (
        r"deepseek.*(r1|reasoner)",
        _p("DeepSeek R1", 2, 5, "reasoning math code", 128),
    ),
    (
        r"deepseek.*(v4|v3\.[12])",
        _p("DeepSeek V3.x", 1, 3, "code reasoning russian", 128),
    ),
    (r"deepseek", _p("DeepSeek V3", 2, 3, "code writing russian", 128)),
    # Moonshot, Qwen, Zhipu, MiniMax
    (r"kimi-k2", _p("Kimi K2", 1, 3, "agentic code writing", 256)),
    (r"kimi", _p("Kimi", 2, 3, "long_context writing research", 200)),
    (
        r"qwen-?3-?coder|qwen.*coder",
        _p("Qwen3 Coder", 1, 2, "code agentic long_context", 262),
    ),
    (r"qwq|qwen.*thinking", _p("Qwen reasoning", 2, 4, "reasoning math", 131)),
    (
        r"qwen-?3.*235b|qwen-?3-max|qwen3\.5",
        _p("Qwen3 235B", 2, 2, "reasoning math russian", 131),
    ),
    (r"qwen.*(vl|omni)", _p("Qwen VL", 3, 3, "vision", 131)),
    (r"qwen", _p("Qwen", 3, 2, "writing math fast", 131)),
    (r"glm-?[\d.]+.*flash", _p("GLM Flash", 4, 1, "fast writing", 128)),
    (r"glm-?4\.?5v|glm.*v\b", _p("GLM Vision", 3, 3, "vision", 64)),
    (r"glm-?(5|4\.[5-9])", _p("GLM 4.5+", 2, 3, "agentic code reasoning", 128)),
    (r"glm", _p("GLM", 3, 2, "writing fast", 128)),
    (r"minimax", _p("MiniMax M", 2, 3, "agentic code long_context", 200)),
    # Meta
    (
        r"llama-?4.*maverick",
        _p("Llama 4 Maverick", 3, 1, "vision fast long_context", 131),
    ),
    (r"llama-?4.*scout", _p("Llama 4 Scout", 3, 1, "fast long_context", 131)),
    (r"llama-?3\.[13]-?(70|405)b", _p("Llama 3.x 70B", 3, 2, "writing fast", 131)),
    (r"llama", _p("Llama (small)", 5, 1, "fast", 131)),
    # Mistral
    (r"magistral", _p("Magistral", 2, 4, "reasoning math", 40)),
    (
        r"codestral|devstral",
        _p("Codestral/Devstral", 2, 2, "code agentic fast", 128),
    ),
    (r"pixtral", _p("Pixtral", 3, 3, "vision", 128)),
    (r"mistral-large", _p("Mistral Large", 2, 3, "writing russian code", 131)),
    (r"mistral-medium", _p("Mistral Medium", 2, 2, "writing code vision", 131)),
    (r"mistral|ministral", _p("Mistral Small", 4, 1, "fast writing", 128)),
    # Others
    (r"nemotron", _p("Nemotron", 3, 2, "reasoning math", 128)),
    (r"command", _p("Command", 3, 3, "research writing", 128)),
    (r"phi-?\d", _p("Phi", 5, 1, "fast", 128)),
    (r"mock|echo", _p("Test model", 5, 1, "fast", 8)),
)
_COMPILED = tuple((re.compile(p, re.IGNORECASE), prof) for p, prof in _FAMILIES)

UNKNOWN = ModelProfile("unknown", 4, 3, (), 32)


def profile_for(model_id: str) -> ModelProfile:
    for pattern, profile in _COMPILED:
        if pattern.search(model_id):
            return profile
    return UNKNOWN


def describe(name: str, model_id: str) -> str:
    """One line of the Orchestrator's model list."""
    p = profile_for(model_id)
    tier = {1: "strongest", 2: "strong", 3: "good", 4: "basic", 5: "small"}[p.tier]
    speed = {1: "very fast", 2: "fast", 3: "medium", 4: "slow", 5: "very slow"}[p.speed]
    best = ", ".join(p.best_at) if p.best_at else "general"
    return f"{name} — {tier}, {speed}, best at: {best}; context {p.context_k}k"


# Models that do not answer an ordinary chat request: speech, pictures, search, embeddings,
# moderation, old completions-only models.
_NOT_CHAT = re.compile(
    r"(embed|whisper|tts|speech|audio|transcri|realtime|image|dall-e|moderation|rerank|"
    r"search-api|search-preview|computer-use|deep-research|davinci|babbage|-instruct$|"
    r"sora|veo|imagen|lyria|guard|ocr)",
    re.IGNORECASE,
)
# On OpenAI's own API these work only through the Responses API, not chat completions.
_OPENAI_RESPONSES_ONLY = re.compile(r"(codex|-pro\b|^o\d+-pro)", re.IGNORECASE)


def chat_capable(model_id: str, *, openai_direct: bool = False) -> bool:
    """Whether a model can do a part of a task (a chat with tools) — the Orchestrator is only
    offered these. ``openai_direct``: the model is served by api.openai.com itself."""
    if _NOT_CHAT.search(model_id):
        return False
    return not (openai_direct and _OPENAI_RESPONSES_ONLY.search(model_id))
