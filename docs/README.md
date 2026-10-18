# SkiiPrep build guide

You write the code; these docs explain **what** to build, **why** it's shaped that way, and **how to check** you got it right.

## How to use it
1. Read [01-requirements.md](01-requirements.md) and [02-system-design.md](02-system-design.md). Edit them until they say what you want. They are yours.
2. Work through the phases in order. Each phase guide has:
   - **Goal**: what exists at the end
   - **Concepts**: the ideas behind it (the "why")
   - **Decisions**: choices to make, with a recommendation
   - **Steps**: what to build, with hints rather than full solutions
   - **Checkpoint**: commands that prove it works
   - **Think about it**: questions to discuss with Claude
3. When you finish a step, ask Claude in the thread to review your code. Ask for a hint any time you're stuck.

## Phases
| # | Phase | Folder | Status |
|---|-------|--------|--------|
| 0 | [Environment setup: uv workspace](phases/phase-00-setup.md) | root, `libs/common/` | ready |
| 1 | [Weather ingest → bronze](phases/phase-01-bronze-ingest.md) | `pipelines/ingestion/` | ready |
| 2 | [Bronze → silver Iceberg table with PySpark](phases/phase-02-silver-iceberg.md) | `pipelines/transformation/` | ready |
| 3 | [API service: FastAPI + DuckDB](phases/phase-03-api.md) | `services/api/` | outline |
| 4 | [MCP server + Claude Desktop](phases/phase-04-mcp-server.md) | `services/mcp_server/` | outline |
| 5 | Snow report source | `pipelines/` | to plan together |
| 6 | Road conditions (WSDOT) | `pipelines/` | to plan together |
| 7 | RAG pipeline: chunking, embeddings, Chroma ([design §8](02-system-design.md#8-rag-pipeline-phase-7)) | `pipelines/`, `services/api/` | designed, to detail together |
| 8 | Your own agent (MCP client) combining SQL tools + RAG | `agents/` | to plan together |
| 9 | Scheduling | `orchestration/` | after data flows end to end |
| 10 | More resorts, cloud | | to plan together |

Later phases are written once we've discussed them, so they reflect what you learned in the earlier ones.
