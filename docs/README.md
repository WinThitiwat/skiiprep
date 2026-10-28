## Project overview

SkiiPrep is a personal ski and snowboard trip assistant. Before a ski day, you usually check the weather forecast, the resort's snow report, and WSDOT for the pass. SkiiPrep brings these together in one assistant you can ask in plain English. Its answers come from fresh data, not from an LLM's memory.

**Scope**
- Single user, running locally on a Mac.
- Starts with Crystal Mountain, WA. Other Ikon and Epic resorts are added as config, not code.

**Questions it should answer**
- **Weather:** how much snow is coming, rain vs. snow at base and summit, wind on the upper lifts, what to wear, and which day looks best.
- **Forecast history:** whether a forecast for a given day has improved or worsened.
- **Snow report and roads:** which lifts are open, whether SR-410 needs chains, and whether Chinook Pass is open.
- **Text (RAG):** what forecasters say about a storm, the avalanche danger, and where to park.

**How it works:** collect → clean → serve → chat
1. **Ingest:** pull from Open-Meteo and keep each raw response unchanged (bronze).
2. **Transform:** PySpark cleans the data into Iceberg tables (silver). MERGE keeps re-runs from duplicating rows.
3. **Serve:** DuckDB answers SQL over those tables, exposed through FastAPI and MCP tools.
4. **Chat:** Claude Desktop calls the MCP tools, so the numbers come from tool results.

**Roadmap**
- Done: weather ingest, Iceberg, and DuckDB outlook.
- Next: FastAPI and MCP server, then snow report, roads (WSDOT), and RAG over text sources (Chroma).
- Later: scheduling, more resorts, and cloud.
----
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
| 5 | [Modernize the design: measure, then optimize](phases/phase-05-modernize-design.md) | `pipelines/transformation/`, `services/api/` | outline |
| 6 | Snow report source | `pipelines/` | to plan together |
| 7 | Road conditions (WSDOT) | `pipelines/` | to plan together |
| 8 | RAG pipeline: chunking, embeddings, Chroma ([design §8](02-system-design.md#8-rag-pipeline-phase-8)) | `pipelines/`, `services/api/` | designed, to detail together |
| 9 | Your own agent (MCP client) combining SQL tools + RAG | `agents/` | to plan together |
| 10 | Scheduling | `orchestration/` | after data flows end to end |
| 11 | [Productionize: Docker and AWS](phases/phase-11-productionize.md) | every component, plus infrastructure | outline |
| 12 | More resorts | `config/resorts.yaml` | to plan together |

Later phases are written once we've discussed them, so they reflect what you learned in the earlier ones.
