# CLAUDE.md — AI Documentation Generator

This file gives Claude Code full context on this project so it can help with
implementation consistently across sessions. Read this before generating or
editing any code in this repo.

---

## 1. What This Project Is

An **agentic AI documentation generator**. A developer provides a project
either as a **Git repo URL** or a **Zip file upload**. The system analyzes the
codebase and automatically generates a structured, 14-section project
documentation file — without the developer having to write it manually.

The system is built as a **multi-agent pipeline orchestrated with LangGraph**,
not a single-shot prompt. Each agent has one narrow responsibility, and agents
pass a shared state object between them.

---

## 2. Why Agentic Architecture (Not a Simple Pipeline)

Do not simplify this into one big prompt or a fixed linear script. The
reasons this project requires an agentic graph:

- **Not every project needs the same sections.** Whether "Database Design" or
  "AI/ML Models" sections apply depends on what's actually detected in the
  codebase — this requires a decision-making step (Planner), not a fixed
  sequence.
- **Repos don't fit in one context window.** Context must be retrieved
  per-section, not dumped in all at once.
- **Output must be verified and self-corrected.** Drafted sections are checked
  against real code facts, and incorrect sections are looped back for retry.
- **Some sections depend on others finishing first** (Abstract/TOC depend on
  Problem Statement, Objectives, Features being done and verified).
- **Different sections need different reasoning strategies** — one
  generalist agent produces shallow/generic output.

---

## 3. Fixed Output Document Structure

Every generated document follows this exact 14-section template. Do not
change section order or numbering. Sections 13 and 14 are conditional.

```
1. Abstract                      (generated LAST — summarizes 3,4,5,6)
2. Table of Contents             (generated LAST — auto-built from final sections)
3. Project Overview
4. Problem Statement
5. Objectives
6. Features
7. System Architecture
8. Technology Stack
9. Folder Structure
10. Installation Guide
11. Configuration
12. API Documentation
13. Database Design              (conditional — only if a DB is detected)
14. AI/ML Models                 (conditional — only if ML libraries/models are detected)
```

---

## 4. Tech Stack

- Python 3.11+
- **LangGraph** — agent orchestration (StateGraph, conditional edges, retry loops)
- **LangChain** — LLM integration helpers
- **Anthropic Claude API** — the LLM provider for all agent reasoning
- **FastAPI** — backend API layer
- **Pydantic** — state schema and validation
- **GitPython** — repo cloning
- **python-dotenv** — environment/config management

---

## 5. Shared State Schema (`GraphState`)

Every agent reads from and writes to this single Pydantic object. Do not
invent parallel state objects — everything flows through this one.

```python
class GraphState(BaseModel):
    source_type: str                # "git" | "zip"
    source_path: str

    project_snapshot: dict          # file_tree, languages, size_stats, entry_points

    code_index: dict                # file_summaries, dependency_graph, detected_frameworks (db/ml/api flags)

    section_plan: dict              # { section_id: bool }  -> which of the 14 sections apply

    sections: dict                  # { section_id: { draft, status, verification_notes, retry_count } }

    final_document: str

    errors: list                    # error/log capture across agents
```

---

## 6. Agent Roster (Do Not Deviate From This Structure)

### Rule of thumb used throughout this project
- **Plain function** → mechanical/deterministic work, no reasoning needed
  (cloning, extracting, scanning folders, formatting/assembly).
- **Agent class (extends `BaseAgent`)** → only where the AI needs to reason,
  decide, summarize, or generate text.
- **Reusable agent class** → when multiple sections share the same drafting
  or checking pattern, use ONE class called multiple times with different
  parameters — do not create a new class per section unnecessarily.

### `BaseAgent` (abstract base — `agents/base_agent.py`)
All agents extend this. It provides:
- `run(self, state: GraphState) -> GraphState` — abstract method every agent implements
- `call_llm(self, prompt: str) -> str` — wraps the Anthropic API call with retry/error handling
- `log_step(self, message: str)` — consistent logging
- `handle_error(self, state, error) -> GraphState` — consistent error capture into `state.errors`

### 1. `IngestionAgent` — mechanical, no LLM calls
- Clones the repo (git) or extracts the zip
- Filters out noise (`node_modules`, `.git`, `dist`, `build`, etc.)
- Builds the raw file tree
- Detects project type via marker files (`package.json`, `requirements.txt`, `pom.xml`)
- Finds the entry point (`main.py`, `index.js`, `app.py`, etc.)
- Output → `state.project_snapshot`
- **Combines steps:** repo/zip normalization + folder scan + entry point detection

### 2. `CodeUnderstandingAgent` — first real LLM agent
- Summarizes files/modules (LLM call: "what does this file do?")
- Builds a dependency/connection graph between files
- Detects signals: database usage, AI/ML libraries, API routes
- Output → `state.code_index`
- **Combines steps:** file summarization + connection mapping + signal detection (all operate on the same input, no benefit to splitting)

### 3. `PlannerAgent`
- Decides which of the 14 sections apply based on `code_index` signals
- Decides section ordering/dependencies (which sections can run in parallel vs. which must wait — e.g. Abstract/TOC always wait)
- Output → `state.section_plan`
- **Combines steps:** "what sections apply" + "what order" is one decision, not two agents

### 4. `SimpleSectionWriterAgent` — REUSABLE, called 4x with different params
- Handles: Tech Stack, Folder Structure, Installation Guide, Configuration
- These are fact-based/deterministic-leaning sections — same class, same
  drafting pattern, different prompt/context per call
- Do NOT create 4 separate classes for these

### 5. Dedicated writer agents — one class each (do NOT merge these)
- `OverviewAgent` → Section 3
- `ProblemObjectivesAgent` → Sections 4 & 5 (generated together, closely linked)
- `FeaturesAgent` → Section 6
- `ArchitectureAgent` → Section 7
- `ApiDocsAgent` → Section 12
- `DatabaseDesignAgent` → Section 13 (only runs if Planner flags a DB)
- `AiMlAgent` → Section 14 (only runs if Planner flags ML)

Each of these needs distinct reasoning/context strategy, so keep them
separate — merging hurts output quality.

### 6. `VerifierAgent` — REUSABLE, called for every section
- Checks each drafted section against real code facts (e.g., does the
  Installation Guide match the actual dependency file? Do listed API routes
  actually exist in code?)
- Pass → mark section done
- Fail → send back to the originating writer agent with correction notes,
  retry up to `max_retries` (from config), then flag for human review as
  fallback
- One class, not one verifier per section

### 7. `SummaryAgent`
- Runs LAST among content agents
- Writes Abstract + Table of Contents
- Only reads already-VERIFIED Problem Statement, Objectives, and Features
  sections — never draft/unverified content

### 8. `assemble_document()` — plain function/class, NOT an agent
- No LLM reasoning involved
- Orders all sections 1–14 (skipping any not applicable)
- Applies consistent formatting, inserts TOC links
- Exports to Markdown / PDF / Docx

---

## 7. LangGraph Orchestration Flow

```
START
  → Ingestion Agent
  → Code Understanding Agent
  → Planner Agent
        │
        ├──(fan-out, parallel)──▶ Section Drafting Agents
        │                              each → Verifier Agent
        │                                        │
        │                             fail → retry loop (back to same drafting agent)
        │                             pass → mark section done
        │
        ▼ (fan-in: wait until all applicable sections verified)
  Summary Agent (Abstract + TOC)
        │
        ▼
  assemble_document()
        │
        ▼
       END
```

Key routing rules:
- Conditional nodes: skip `DatabaseDesignAgent` / `AiMlAgent` entirely if
  Planner didn't flag them — don't waste LLM calls.
- Retry loop is per-section, not global — a failure in one section must not
  force re-drafting of unrelated sections.
- `SummaryAgent` has a hard dependency edge: cannot run until Problem
  Statement, Objectives, and Features are verified.
- Use LangGraph's checkpointer after major stages (Ingestion, Planning, each
  verified section) so large repos can resume instead of restarting from
  scratch on failure.

---

## 8. Recommended Build Order

Build bottom-up along the real data flow. Get ONE full path working
end-to-end before adding breadth — do not implement all drafting agents at
once.

1. Make `BaseAgent.call_llm()` fully real (Anthropic API call, error handling, retries)
2. `IngestionAgent` — pure code, no LLM, test standalone first
3. `CodeUnderstandingAgent` — start with rule-based language/file-tree detection, then add LLM summarization; test on a small repo first
4. Pick ONE simple drafting agent first (Tech Stack or Folder Structure) — easiest to verify correctness of
5. Build `VerifierAgent` against that one section
6. Wire the minimal LangGraph flow: Ingestion → Code Understanding → one Drafting Agent → Verifier → retry loop. Prove this works end-to-end.
7. Add `PlannerAgent`; test against sample projects with/without DB, with/without ML
8. Expand to remaining drafting agents in this order (easiest → hardest):
   Folder Structure → Tech Stack → Installation Guide → Configuration →
   API Documentation → Database Design → Architecture → Features →
   Overview → Problem Statement/Objectives → AI/ML Models
9. `SummaryAgent` — only once core sections reliably pass verification
10. `assemble_document()` — deterministic formatting, build last
11. Wrap with FastAPI endpoints (`POST /generate/git`, `POST /generate/zip`, `GET /status/{job_id}`)
12. Test on real, varied repos: small, large, with DB, with ML, poorly structured

---

## 9. Coding Conventions

- Every agent MUST extend `BaseAgent` — no standalone agent classes.
- Every LangGraph node function is a thin wrapper around an agent class, e.g.:
  ```python
  def code_understanding_node(state: GraphState) -> GraphState:
      return CodeUnderstandingAgent(...).run(state)
  ```
- Do not let drafting agents read raw code directly — they should only read
  from `state.code_index`, which is the single source of truth built by
  `CodeUnderstandingAgent`.
- Do not add a new agent class for a section unless its reasoning/context
  needs are genuinely different from existing reusable agents — check
  Section 6 above first.
- Keep `assemble_document()` and `IngestionAgent` free of LLM calls entirely
  — they are mechanical by design.
- Config values (API key, model name, `max_retries`, temp storage path) live
  in `config.py` / `.env` — never hardcode them in agent files.

---

## 10. What NOT To Do

- Do not collapse this into a single-prompt "read repo, write whole doc" flow — defeats the purpose of the whole architecture.
- Do not create a separate agent class per section for the deterministic ones (Tech Stack, Folder Structure, Installation, Configuration) — use `SimpleSectionWriterAgent`.
- Do not let `SummaryAgent` run before its dependent sections are verified.
- Do not skip the Verifier step "to save time" — hallucinated install commands, fake API routes, or invented DB tables are the main failure mode this architecture exists to prevent.
- Do not make `assemble_document()` an LLM agent — it's pure formatting logic.
