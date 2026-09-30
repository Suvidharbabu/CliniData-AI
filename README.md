# CliniData AI

A showcase website plus a live Graph-RAG demo for healthcare and life-sciences compliance, based on the ECRIP v2.0 design
(Graph RAG, hybrid retrieval, agentic AI and human-in-the-loop approvals), adapted to HIPAA, GDPR health data, 21 CFR Part 11,
ICH E6(R3)/E2A, the DPDP Act 2023 and ISO 27001.

- **Frontend:** plain HTML5/CSS/JavaScript, built with Vite (`frontend/`)
- **Backend:** Python FastAPI (`backend/`), served on Vercel as a serverless function (`api/index.py`)
- **Data:** Supabase Postgres (relational data, full-text sparse search, auth), Neo4j AuraDB (knowledge graph), Pinecone (dense search, codebook routing, reranking)
- **LLM:** Claude via the Anthropic API (`claude-opus-5-5` writes the cited answer; `claude-haiku-4-5` writes the HyDE passage)

The demo tenant ("Meridian Clinical Research") is fictional, and regulation texts are paraphrased. Nothing here is legal advice.

## How a demo query runs

`POST /api/v1/agent/query` runs the steps in `backend/app/services/pipeline.py`:

1. **Orchestrator:** scopes frameworks and articles from the question and routes the top-5 codebook instructions (Pinecone `codebook` namespace, blended with each instruction's success rate).
2. **Retriever:** Claude Haiku writes a HyDE passage. Pinecone dense top-20 and Postgres full-text top-20 run in parallel, are fused with RRF (k=60), and are reranked to the top 10 by `bge-reranker-v2-m3`.
3. **Graph traversal:** Neo4j expansion from the retrieved nodes to their regulations, controls, evidence, risks and `MAPS_TO` equivalents.
4. **Gap Mapper, Constraint Verifier, Cross-Reference Agent, Risk Scorer:** deterministic rules in `services/gaps.py`.
5. **Regulatory Reporter:** Claude writes a cited answer from the serialised subgraph.
6. **Hallucination guard:** checks every `[NODE-ID]` citation against the subgraph (`services/guard.py`).
7. **Approval gate:** CRITICAL gaps go to the CCO and HIGH gaps to a compliance manager. Approving one creates a remediation task.

## Setup

### 1. Services

| Service | What to create | Values you need |
|---|---|---|
| Supabase | A project. Run `db/schema.sql` in **SQL Editor**. Under **Authentication → Providers**, keep Email enabled. | Project URL, anon/publishable key, the **Transaction pooler** connection string (port 6543) |
| Neo4j AuraDB | A free instance | URI (`neo4j+s://…`), username, password |
| Pinecone | Only an API key; `seed.py` creates the index | API key |
| Anthropic | An API key at console.anthropic.com | API key |

Copy `.env.example` to `.env` and fill in the values.

### 2. Local run

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt pytest uvicorn

python -m scripts.seed             # loads Postgres + Neo4j + Pinecone (safe to re-run)
pytest backend/tests               # unit tests (no network needed)
uvicorn backend.app.main:app --reload --port 8000

cd frontend
npm install
npm run dev                        # http://localhost:5173, which proxies /api to :8000
```

Check `http://localhost:8000/api/ready`: it should report `ok` for postgres, neo4j, pinecone and anthropic.

### 3. Deploy to Vercel

1. Push this folder to a GitHub repository.
2. In Vercel, **Add New → Project**, import the repo, and keep the root directory as the repo root. `vercel.json` already sets the build (`frontend/dist`) and the Python function (`api/index.py`).
3. Add every variable from `.env.example` under **Settings → Environment Variables**. The `VITE_*` ones are needed at build time.
4. Deploy, then open `https://<your-app>.vercel.app/api/ready`.
5. In Supabase, go to **Authentication → URL Configuration**, set the Site URL to your Vercel domain, and add it to the redirect URLs.

## Notes

- **Neo4j AuraDB Free pauses after about 3 days of inactivity.** Resume it from the Aura console; `/api/ready` shows when it is down.
- **Cost:** each demo query makes one Opus 5.5 call (low effort) and one small Haiku call. Each user is capped at `DAILY_QUERY_LIMIT` queries per 24 h. Set `ANTHROPIC_MODEL=claude-haiku-4-5` to reduce cost.
- **Security:** the browser only ever holds the Supabase anon key. All tables have RLS enabled with no policies, so data is reachable only through the FastAPI backend, which verifies the Supabase JWT (JWKS or legacy HS256 secret). `audit_logs` is append-only and enforced by a trigger.
- **Demo roles:** signed-in users can switch role (compliance officer, compliance manager, CCO, auditor) to try the approval paths. Runs, gaps and approvals are scoped per user.

## Layout

```
api/index.py               Vercel entry point
backend/app/               FastAPI app: config, auth, db, graph, vector, routers/, services/
backend/tests/             pytest unit tests (RRF, guard, EMA, gap rules on seed data)
db/schema.sql              Supabase schema + RLS
scripts/seed_data.py       Demo dataset (single source of truth)
scripts/seed.py            Loads the dataset into Postgres, Neo4j and Pinecone
frontend/                  Vite multi-page site (11 pages) + src/js, src/css
```
