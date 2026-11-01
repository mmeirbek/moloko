# @moloko/agent-contracts

JSON Schemas for the realtime contracts shared by the API and clients:

- `schemas/event-envelope.schema.json` — one event of the append-only log (spec 10.1)
- `schemas/ws-frames.schema.json` — frames on `/ws/v1/events` (spec 11)

The TypeScript mirror lives in `packages/shared-types/src/events.ts`; backend tests
validate real events against these schemas. Agent↔agent messages (spec 14.4) are
added in Sprint 4.
