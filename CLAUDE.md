# SkiiPrep: guidance for Claude

SkiiPrep is Win's personal ski/snowboard trip assistant: data pipelines (weather, snow report, roads, text for RAG) feed an Iceberg lake, served by FastAPI and exposed to Claude Desktop through MCP. Read `docs/01-requirements.md` and `docs/02-system-design.md` before suggesting changes; they are the agreed spec.

## Ways of working (most important)
This is a **learning project. Win writes the code.**
- **Don't write or edit code unless Win explicitly asks** for that specific piece. Default to explaining, hinting, reviewing and asking questions.
- **Explain the why.** For any suggestion, give the reason and the main alternative, briefly.
- **Ask before deciding.** Confirm that Win agrees before any design change, new dependency, new folder, or a change to the docs' decisions. Record agreed decisions in the decision tables (`D#` in requirements, `SD#`/`R#` in system design).
- **Hints before answers.** When Win is stuck: first a pointer to the concept or doc, then a hint, then a small snippet. Never jump to the full solution unless asked.
- **Reviews:** point out bugs first, then design or guardrail issues, then style. Say which are must-fix and which are optional.
- **Never commit, push or open PRs** unless Win asks.
- Follow the phase guides in `docs/phases/` and keep them in sync with what was actually built.

## Architecture guardrails
Flag any code that breaks one of these, and explain why it matters.
1. **Bronze is immutable.** Raw responses are saved exactly as received, one file per fetch, with the lineage envelope. Never edit or overwrite bronze.
2. **Single writer.** Only components in `pipelines/` write data (`ingestion` → bronze, `transformation` → Iceberg, `rag` → Chroma). Everything in `services/` only reads.
3. **Front door.** Consumers (MCP, agents) get data through the FastAPI service over HTTP, never by reading the lake directly.
4. **No cross-imports between components.** Shared code goes in `libs/common/`. `services/mcp_server/` doesn't depend on it.
5. **Put new components in the right group:** `pipelines/` (writes), `services/` (long-running, read only), `libs/` (shared, no side effects), `agents/`. Ask Win before adding a new group.
6. **Idempotent jobs.** Re-running any job on the same input changes nothing (MERGE on the table's grain, content hashes for chunks).
7. **UTC everywhere** in storage; convert to the resort's timezone only when serving.
8. **Units in column and field names** (`snowfall_cm`, `gust_kmh`).
9. **Config, not code, for resorts.** Nothing is hard-coded to Crystal Mountain; resorts come from `config/resorts.yaml`.
10. **Numbers come from SQL, prose from RAG.** LLM answers must be grounded in tool results, which include `fetched_at` or `issued_at`.
11. **Vector store is rebuildable** from `docs.chunks` in Iceberg; it's never the source of truth.

## Code conventions
- Python 3.12, managed with **uv** (workspace; one package per component, glob members by group). Add dependencies to the member that needs them: `uv add --package <member> <dep>`.
- Type hints on public functions. Pydantic for config and API models; dataclasses are fine internally.
- Small, single-purpose functions; pass dependencies in (e.g. an `httpx.Client`) so they can be tested.
- HTTP: always set timeouts, call `raise_for_status()`, and respect each source's rate limits and terms. Send a descriptive `User-Agent` where a source asks for one (NWS does).
- Paths come from `skiiprep_common.settings`, never hard-coded absolute paths.
- Secrets (e.g. the WSDOT key) go in `.env` (git-ignored) and are read via settings. Never commit them.
- Logging with the `logging` module, not `print`, outside CLIs.
- Name packages `skiiprep_*`. Never name a module after a library you use (e.g. `mcp`).

## Testing
- `pytest`. Tests **never call real APIs**: use `httpx.MockTransport` and small fixture payloads.
- Write files under pytest's `tmp_path`, never into `data/`.
- Spark tests are slower; mark them `@pytest.mark.spark` so `uv run pytest -m "not spark"` stays quick.
- Every job gets an idempotency test: run twice, assert nothing changed.

## Git
- Small commits whose messages say why. Never commit `data/`, `.venv/` or `.env`.

## Commands
```bash
uv sync --all-packages          # install every member
uv run pytest -m "not spark"    # fast tests
uv run ingest weather           # bronze
uv run transform weather        # Iceberg silver
```
