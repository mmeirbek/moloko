"""Every agent is an exotic animal: the owner picks one or leaves it to chance (the office's
least used species), agents the Orchestrator creates get one at random, the Orchestrator
stays the moloko cow (no animal of its own)."""

from __future__ import annotations

import random

from fastapi import FastAPI
from sqlalchemy import select

from app.agents.looks import ANIMALS, pick_animal
from app.models import Agent, User
from tests.conftest import (
    RecordingQueue,
    add_mock_model,
    create_agent,
    csrf_headers,
    drain,
    logged_in_client,
)


async def test_the_owner_picks_an_animal_or_gets_the_least_used_one(
    app: FastAPI, owner: User
) -> None:
    async with logged_in_client(app) as client:
        headers = await csrf_headers(client)
        tiger = await create_agent(client, name="Tiger", animal="amur_tiger")
        assert tiger["animal"] == "amur_tiger"
        others = [await create_agent(client, name=f"Agent {i}") for i in range(len(ANIMALS) - 1)]
        # nothing chosen: a species nobody has yet, until every one is taken once
        assert sorted(a["animal"] for a in [tiger, *others]) == sorted(ANIMALS)

        changed = await client.patch(
            f"/api/v1/agents/{tiger['id']}", json={"animal": "manul"}, headers=headers
        )
        assert changed.status_code == 422  # only the known species
        changed = await client.patch(
            f"/api/v1/agents/{tiger['id']}", json={"animal": "pallas_cat"}, headers=headers
        )
        assert changed.status_code == 200, changed.text
        assert changed.json()["animal"] == "pallas_cat"
        kept = await client.patch(
            f"/api/v1/agents/{tiger['id']}", json={"description": "Fast"}, headers=headers
        )
        assert kept.json()["animal"] == "pallas_cat"  # omitted = unchanged


async def test_pick_animal_takes_one_of_the_fewest(app: FastAPI, owner: User) -> None:
    seeded = random.Random
    async with app.state.db.sessionmaker() as db:
        for animal in ANIMALS[:-1]:
            db.add(Agent(user_id=owner.id, name=animal, agent_type="autonomous", animal=animal))
        await db.flush()
        assert await pick_animal(db, owner.id, seeded(1)) == ANIMALS[-1]
        db.add(Agent(user_id=owner.id, name="last", agent_type="autonomous", animal=ANIMALS[-1]))
        await db.flush()
        picks = {await pick_animal(db, owner.id, seeded(seed)) for seed in range(40)}
        assert len(picks) > 1 and picks <= set(ANIMALS)  # all tied again: any of them


async def test_agents_the_orchestrator_creates_get_an_animal_and_it_stays_the_cow(
    app: FastAPI, owner: User, queue: RecordingQueue
) -> None:
    async with logged_in_client(app) as client:
        await add_mock_model(client)
        resp = await client.post(
            "/api/v1/runs",
            json={"title": "Build it [[mock:plan:2]]"},
            headers=await csrf_headers(client),
        )
        assert resp.status_code == 200, resp.text
        await drain(app, queue)
    async with app.state.db.sessionmaker() as db:
        agents = list((await db.execute(select(Agent))).scalars())
    boss = [a for a in agents if a.agent_type == "orchestrator"]
    made = [a for a in agents if a.agent_type != "orchestrator"]
    assert boss and boss[0].animal is None
    assert made and all(a.animal in ANIMALS for a in made)
