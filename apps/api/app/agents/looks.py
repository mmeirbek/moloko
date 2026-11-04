"""Every agent is an animal (owner's decision 2026-11-03: exotic, specific species — an Amur
tiger, not just a tiger). The owner picks one for a new agent or leaves it to chance; agents
the Orchestrator creates get one at random. The faces are drawn in the web app
(apps/web/features/agents/agent-avatar.tsx); the moloko cow is the Orchestrator's alone."""

from __future__ import annotations

import random
import uuid
from collections import Counter
from typing import Literal, get_args

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent

Animal = Literal[
    "amur_tiger",
    "snow_leopard",
    "pallas_cat",
    "fennec_fox",
    "red_panda",
    "capybara",
    "axolotl",
    "quokka",
    "okapi",
    "tarsier",
    "ring_tailed_lemur",
    "malayan_tapir",
    "sea_otter",
    "atlantic_puffin",
    "three_toed_sloth",
    "platypus",
    "barn_owl",
    "saiga",
    "mandrill",
    "emperor_tamarin",
]
ANIMALS: tuple[str, ...] = get_args(Animal)


async def pick_animal(
    db: AsyncSession, user_id: uuid.UUID, rng: random.Random | None = None
) -> str:
    """A random animal among the ones the office has fewest of (so faces rarely repeat)."""
    rows = await db.execute(
        select(Agent.animal).where(
            Agent.user_id == user_id, Agent.archived_at.is_(None), Agent.animal.is_not(None)
        )
    )
    used = Counter(a for a in rows.scalars() if a in ANIMALS)
    fewest = min(used.get(a, 0) for a in ANIMALS)
    choices = [a for a in ANIMALS if used.get(a, 0) == fewest]
    return (rng or random).choice(choices)
