"""
GraphState — the single shared state object for the agent pipeline.

Every agent reads from and writes to this one Pydantic model (CLAUDE.md §5).
Do not create parallel state objects; everything flows through here.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GraphState(BaseModel):
    """Shared state passed between all agents in the LangGraph pipeline."""

    # --- Input (set at ingestion) ---
    source_type: str = ""           # "git" | "zip"
    source_path: str = ""           # local path to the ingested project

    # --- IngestionAgent output ---
    # file_tree, languages, project_type, sub_projects, entry_points, size_stats
    project_snapshot: dict = Field(default_factory=dict)

    # --- CodeUnderstandingAgent output ---
    # file_summaries, dependency_graph, detected_frameworks (db/ml/api flags)
    code_index: dict = Field(default_factory=dict)

    # --- PlannerAgent output ---
    # { section_id: bool } -> which of the 14 sections apply
    section_plan: dict = Field(default_factory=dict)

    # --- Writer/Verifier working area ---
    # { section_id: { draft, status, verification_notes, retry_count } }
    sections: dict = Field(default_factory=dict)

    # --- assemble_document() output ---
    final_document: str = ""

    # --- Cross-agent error/log capture ---
    errors: list = Field(default_factory=list)
