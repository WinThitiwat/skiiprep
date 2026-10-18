# 01 · Requirements

> Status: **agreed 2026-10-15.** Q1–Q9 will grow as we build.

## 1. Problem
Before a ski/snowboard day I check several sites: the weather forecast, the resort's snow report, and WSDOT for the pass. I want one assistant I can ask in plain English, and I want its answers to come from real, fresh data rather than an LLM's guess.

## 2. Users and scope
- **User:** me (single user, personal project).
- **Resorts:** Crystal Mountain, WA first. Later, more Ikon and Epic resorts (US, Canada, maybe Japan/Europe), so nothing may be hard-coded to Crystal.
- **Runs:** locally on my Mac. Cloud is a later phase.
- **Goal beyond the product:** learn data engineering + agentic AI end to end, so clarity beats cleverness.

## 3. Questions the assistant must answer
This list is the real spec: every table and tool we build should trace back to a row here.

| ID | Question (example wording) | Data needed | Phase |
|----|----------------------------|-------------|-------|
| Q1 | "How much snow is coming to Crystal in the next 3 days?" | hourly snowfall forecast | Weather |
| Q2 | "Will it rain at the base or snow?" | temp + freezing level at base vs summit | Weather |
| Q3 | "Is it too windy for the upper lifts Saturday?" | wind speed and gusts at summit | Weather |
| Q4 | "What should I wear?" | temp, feels-like, precip, wind | Weather |
| Q5 | "Which day this week looks best?" | daily rollup of Q1–Q4 | Weather |
| Q6 | "Did the forecast for Saturday get better or worse?" | forecast history (every fetch kept) | Weather |
| Q7 | "What did Crystal report this morning? Which lifts are open?" | resort snow report | Snow report |
| Q8 | "Do I need chains on SR-410? Is Chinook Pass open?" | WSDOT road conditions | Roads |
| Q9 | "What are forecasters saying about this storm? How confident are they?" | NWS forecast discussion text | RAG |
| Q10 | "What's the avalanche danger if I go into the sidecountry?" | NWAC avalanche forecast text | RAG |
| Q11 | "Where should I park on a busy Saturday?" | Resort guides (offline docs) | RAG |

> **Your turn:** add, remove or reword questions. Anything you'd actually ask on a Thursday night before a trip belongs here.

## 4. Functional requirements
- **FR1 Ingest:** pull data from each source on demand (later on a schedule) and keep the raw response exactly as received.
- **FR2 Store:** keep clean, typed, history-preserving tables in an Iceberg data lake.
- **FR3 Query:** answer Q1–Q9 with SQL over those tables.
- **FR4 Serve:** expose those answers through a FastAPI HTTP API and as MCP tools.
- **FR5 Chat:** use Claude Desktop as the chat client, calling the MCP tools.
- **FR6 Multi-resort:** adding a resort means adding config, not code.
- **FR7 Text search (RAG):** chunk, embed and index text sources in a vector database (Chroma), and answer prose questions with citations to the source passage and its issue time.

## 5. Non-functional requirements
| Area | Requirement | Why |
|------|-------------|-----|
| Correctness | Numbers in answers come from tool results, never from the model's memory | The whole point of the project |
| Freshness | Each answer can say when its data was fetched | So you know if you're looking at a stale forecast |
| Reproducibility | Any table can be rebuilt from raw files | Lets you fix transform bugs without re-fetching |
| Idempotency | Re-running a job never duplicates data | Safe to retry |
| Cost | $0: free APIs, local tools | Personal project |
| Politeness | Respect source rate limits and terms | Open-Meteo is free for non-commercial use |
| Portability | Local first, cloud later with config changes, not rewrites | Phase plan |

## 6. Data sources
| Data | Source | Notes |
|------|--------|-------|
| Weather | **Open-Meteo** forecast API (chosen) | No key, global, can target an elevation |
| Weather text | NWS Area Forecast Discussion | For RAG |
| Avalanche text | NWAC forecasts | For RAG; check terms of use |
| Resort guides | Downloaded once (offline) | For RAG |
| Snow report | Crystal's site or a snow-report provider | To be researched in that phase |
| Roads | WSDOT Traveler Information API | Free key; SR-410 and Chinook Pass |

## 7. Out of scope (for now)
Other users and login, mobile app, alerts and notifications, making our own avalanche forecasts (we only *retrieve* NWAC's), booking lift tickets.

## 8. Decisions log
| # | Decision | Chosen | Date |
|---|----------|--------|------|
| D1 | First resort | Crystal Mountain | 2026-10-15 |
| D2 | Build order | weather, snow report, roads | 2026-10-15 |
| D3 | Weather source | Open-Meteo | 2026-10-15 |
| D4 | Stack | Python (PySpark) + uv + Iceberg + DuckDB + FastAPI + MCP | 2026-10-15 |
| D5 | Chat client | Claude Desktop via MCP | 2026-10-15 |
| D6 | Ways of working | Win writes the code; Claude explains and reviews | 2026-10-15 |
| D7 | Architecture | See system design SD6–SD11 (Hadoop catalog, DuckDB read-only, MCP→API over HTTP, manual runs, uv workspace) | 2026-10-15 |
| D8 | RAG | Build a RAG pipeline for text sources with Chroma; design in system design §8 | 2026-10-15 |
| D9 | Code layout | Components grouped by role: `pipelines/`, `services/`, `libs/`, `agents/` (system design SD12) | 2026-10-18 |
