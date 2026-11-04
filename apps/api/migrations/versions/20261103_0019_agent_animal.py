"""Owner's decision: every agent is an exotic animal (its face and office character).

* ``agents.animal`` — one of the species in ``app/agents/looks.py``; NULL for the
  Orchestrator (the moloko cow). Existing agents get one now: oldest first, the species the
  office has fewest of, chosen from the agent's id (the same result on every database).

Revision ID: 0019_agent_animal
Revises: 0018_full_access_all
Create Date: 2026-11-03 21:00:00+00:00
"""

import random
from collections import Counter, defaultdict
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_agent_animal"
down_revision: str | Sequence[str] | None = "0018_full_access_all"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# A copy as of this migration (the app's list may grow later).
SPECIES = (
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
)


def upgrade() -> None:
    op.add_column("agents", sa.Column("animal", sa.String(length=40), nullable=True))
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT id, user_id FROM agents WHERE agent_type <> 'orchestrator' "
            "ORDER BY created_at, id"
        )
    ).all()
    used: dict[object, Counter[str]] = defaultdict(Counter)
    for agent_id, user_id in rows:
        counts = used[user_id]
        fewest = min(counts.get(s, 0) for s in SPECIES)
        animal = random.Random(str(agent_id)).choice(  # noqa: S311 — a face, not a secret
            [s for s in SPECIES if counts.get(s, 0) == fewest]
        )
        counts[animal] += 1
        bind.execute(
            sa.text("UPDATE agents SET animal = :animal WHERE id = :id"),
            {"animal": animal, "id": agent_id},
        )


def downgrade() -> None:
    op.drop_column("agents", "animal")
