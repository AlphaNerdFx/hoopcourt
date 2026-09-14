"""FastAPI application.

BUILD_SEQUENCE.md Step 5 defines request schemas and a router class but never
assembles an app -- there is no ``FastAPI()``, no route, and no ``uvicorn`` entry
point anywhere in its 2,372 lines. This module is that missing assembly: it wires
token gating -> temporal routing -> era-isolated retrieval -> (optional)
generation into a servable API.

    uvicorn src.api.main:app --reload
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.router import MAX_PROMPT_TOKENS, TemporalRouter, retrieval_text
from src.api.tokens import build_counter
from src.db.connection import engine_versions, get_vector_db_connection
from src.db.schema import (
    ambiguous_seasons,
    coverage_bounds,
    migrate,
    nearest_covered_season,
    resolve_era_documents,
)
from src.db.search import retrieve_segmented_context, retrieve_timeline
from src.ingest.embedder import Embedder
from src.ingest.indexer import index_integrity
from src.model.generation import build_generator, lookup_concept_analogy
from src.model.prompt_templates import format_citation
from src.model.verify import verify_citations

STATIC_DIR = Path(__file__).parent / "static"
DB_PATH = os.environ.get("NBA_LEGAL_DB", "nba_legal.db")
BACKEND_MODE = os.environ.get("BACKEND_MODE", "local")

state: dict[str, Any] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Loaded once: the embedding model costs seconds to load and the token
    # gate must not pay that per request.
    state["embedder"] = Embedder()
    # Load the embedding model before serving. Deferring it to the first request
    # made a user pay several seconds and, under concurrent first-requests, raced
    # the lazy initialiser into a meta-tensor error. Startup is the right place
    # for a cost that every request depends on.
    state["embedder"].warm()
    # NBA_TOKEN_COUNTER=local|cloud opts into exact counting; see tokens.py.
    state["counter"] = build_counter("cloud" if BACKEND_MODE == "cloud" else "auto")
    # None when no backend is installed. The API still serves cited sources --
    # retrieval is the part that has to be right; prose is the optional layer.
    state["generator"] = build_generator(BACKEND_MODE)
    # Derived once from the index: which four-digit years need clarifying depends
    # entirely on where the document windows fall.
    try:
        conn = get_vector_db_connection(DB_PATH)
        # An index built before a schema addition would otherwise fail on the
        # first query rather than at startup. Requests open their own connection
        # and never migrate, so this is the one place it can happen once.
        for change in migrate(conn):
            print(f"[migration] {change}")
        state["ambiguous_years"] = ambiguous_seasons(conn)
        conn.close()
    except Exception:
        state["ambiguous_years"] = None
    yield
    state.clear()


logger = logging.getLogger("hoopcourt.api")

app = FastAPI(
    title="Hoopcourt",
    description="Era-aware retrieval over NBA governing documents.",
    version="1.0.0",
    lifespan=lifespan,
)


def get_conn():
    # SQLite connections are not shareable across threads; one per request keeps
    # this correct under uvicorn's threadpool without a global lock.
    conn = get_vector_db_connection(DB_PATH)
    try:
        yield conn
    finally:
        conn.close()


class QueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=20_000)
    style: Literal["scholar", "casual"] = "scholar"
    clarified_season: str | None = Field(
        default=None, pattern=r"^\d{4}-\d{2}$",
        description='Resolves an ambiguous year, e.g. "2023-24".',
    )
    k: int = Field(default=5, ge=1, le=20)


class Source(BaseModel):
    document: str
    source_tier: str = "primary"
    article: str | None = None
    section: str | None = None
    page: int
    citation: str
    distance: float
    excerpt: str


class Coverage(BaseModel):
    """Why a query returned nothing, when it did.

    Empty sources previously meant either "no document covers this era" or "no
    passage matched" with no way to tell them apart -- so a user asking about
    1952 got the same silence as one asking a badly-worded modern question."""
    season: int | None
    covered: bool
    earliest_season: int | None = None
    latest_season: int | None = None
    nearest_covered_season: int | None = None
    reason: str | None = None      # era_not_covered | no_match | ambiguous_season
    message: str | None = None


class Grounding(BaseModel):
    """Whether the generated answer only cited what it was given.

    Reported at runtime, not just in the evaluation, because the failure it
    catches is invisible in the answer itself: a real document carrying an
    invented pinpoint reads exactly like a correct citation. Measured at 70% on
    a local 7B, so a caller that displays answers should look at this.
    """
    checked: bool = False
    citations: int = 0
    supported: int = 0
    fabricated: list[str] = []
    uncited_claim: bool = False
    trustworthy: bool = True


class QueryResponse(BaseModel):
    # A misspelled or missing field would otherwise be dropped in silence.
    model_config = ConfigDict(extra="forbid")

    query: str
    route_action: str
    target_year: int | None
    trigger_keyword: str | None
    sources: list[Source]
    timeline: list[Source] = []
    coverage: Coverage
    answer: str | None = None
    grounded: bool
    grounding: Grounding = Grounding()


@app.get("/health")
def health(conn=Depends(get_conn)) -> dict[str, Any]:
    try:
        stats = index_integrity(conn)
    except Exception as exc:
        raise HTTPException(503, f"index unavailable: {exc}") from exc
    return {
        "status": "ok" if stats["vectors"] else "empty-index",
        "backend_mode": BACKEND_MODE,
        "token_counter": state.get("counter").name if state.get("counter") else None,
        "generator": state["generator"].name if state.get("generator") else None,
        "ambiguous_years": sorted(state.get("ambiguous_years") or []),
        "engine": engine_versions(conn),
        "index": stats,
    }


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest, conn=Depends(get_conn)):
    # 1. Token gate, before any retrieval work is done.
    counter = state.get("counter")
    counted = counter.count(request.query) if counter else 0
    if counted > MAX_PROMPT_TOKENS:
        raise HTTPException(
            400,
            detail={
                "error": "prompt_too_long",
                "message": (
                    f"Prompts are strictly capped at {MAX_PROMPT_TOKENS:,} tokens "
                    f"to ensure retrieval accuracy. Your input was {counted:,} tokens."
                ),
                "counted_tokens": counted,
                "limit": MAX_PROMPT_TOKENS,
                "counter": counter.name,
            },
        )

    # 2. Route to an era.
    route = TemporalRouter.resolve_query_route(
        request.query, request.clarified_season, state.get("ambiguous_years"))

    # 3. An ambiguous year suspends the search rather than guessing a season.
    # 409 Conflict, not the spec's HTTP 300: 300 Multiple Choices is a redirect
    # status, and clients, proxies and browsers treat it as one. PRD User Story 1
    # describes a UI clarification prompt, which is not a redirect.
    if route["route_action"] == "require_season_clarification":
        return JSONResponse(
            status_code=409,
            content={
                "error": "season_ambiguous",
                "message": (
                    f"\"{route['target_year']}\" could mean either season. "
                    "Which did you mean?"
                ),
                "year": route["target_year"],
                "options": route.get("options", []),
                "resend_with": "clarified_season",
            },
        )

    # 4. Era-isolated retrieval, in two channels. Authoritative sources answer
    # "what was the rule"; curated timeline entries answer "when did it change"
    # and are kept separate so a summary can never outrank the governing text.
    # Not request.query: an explicit year is already consumed by the era
    # filter, and leaving it in the embedded text pulls dated worked
    # examples ahead of the provision that states the rule. See
    # router.retrieval_text.
    embedding = state["embedder"].embed_query(retrieval_text(request.query, route))
    rows = retrieve_segmented_context(conn, embedding, route, k=request.k)
    timeline_rows = retrieve_timeline(conn, embedding, route, k=3)

    def to_source(r: dict) -> Source:
        return Source(
            document=r["document"], article=r["article"], section=r["section"],
            page=r["page"], citation=format_citation(r), distance=r["distance"],
            excerpt=r["text"][:400], source_tier=r.get("source_tier", "primary"),
        )

    sources = [to_source(r) for r in rows]
    timeline = [to_source(r) for r in timeline_rows]

    # 5. Say why, when there is nothing to say.
    season = route["target_year"]
    bounds = coverage_bounds(conn)
    era_docs = resolve_era_documents(conn, int(season)) if season is not None else []
    if era_docs:
        covered = True
        reason = None if (sources or timeline) else "no_match"
        message = None if reason is None else (
            f"The index covers {season}, but no passage matched this question.")
    else:
        covered = False
        reason = "era_not_covered"
        near = nearest_covered_season(conn, int(season)) if season is not None else None
        span = f"{bounds[0]}-{bounds[1]}" if bounds else "nothing"
        message = (f"No source in this index covers the {season} season. "
                   f"Coverage runs {span}"
                   + (f"; the nearest covered season is {near}." if near else "."))
    coverage = Coverage(
        season=season, covered=covered,
        earliest_season=bounds[0] if bounds else None,
        latest_season=bounds[1] if bounds else None,
        nearest_covered_season=(nearest_covered_season(conn, int(season))
                                if season is not None and not covered else None),
        reason=reason, message=message,
    )

    answer = None
    grounding = Grounding()
    generator = state.get("generator")
    if generator is not None and sources:
        analogy = (lookup_concept_analogy(conn, route.get("trigger_keyword"))
                   if request.style == "casual" else None)
        try:
            answer = generator.generate(request.query, rows, route,
                                        style=request.style, analogy=analogy)
        except Exception:
            # A generation backend that fails must not discard retrieval that
            # succeeded. The contract already allows answer=null when no backend
            # is installed; a backend that errored is the same situation from the
            # caller's side, and the sources are still worth returning. Raising
            # here turned a working 200 with five correct citations into a 500.
            logger.exception("generation failed; returning sources only")
            answer = None

    # The answer is checked against the chunks it was actually handed. A
    # citation to a genuine document that was not in context is still invented:
    # the model produced a pinpoint it could not have read.
    if answer is not None:
        report = verify_citations(answer, rows + timeline_rows)
        grounding = Grounding(
            checked=True, citations=report.total,
            supported=len(report.supported), fabricated=report.fabricated,
            uncited_claim=report.uncited_claim, trustworthy=report.ok,
        )

    return QueryResponse(
        query=request.query,
        route_action=route["route_action"],
        target_year=route["target_year"],
        trigger_keyword=route["trigger_keyword"],
        sources=sources,
        timeline=timeline,
        coverage=coverage,
        answer=answer,
        grounding=grounding,
        # No sources means no grounded answer is possible. Saying so is the
        # correct outcome, not a degraded one (CLAUDE.md sec.2.2).
        grounded=bool(sources),
    )


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """The single-page UI.

    Served from the API itself rather than a separate front end: this is a tool
    people install, and requiring a second process, a build step or a package
    manager to see its own output would be a worse product for no gain. No
    dependencies, no bundler, one file.
    """
    return FileResponse(STATIC_DIR / "index.html")
