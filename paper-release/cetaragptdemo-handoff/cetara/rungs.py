"""The four ladder rungs (all share the same Gemini base model).

  Rung 1: Vanilla LLM       - no data, no tools
  Rung 2: Stuffed-context   - entire dataset injected into the system prompt
  Rung 3: Structured RAG    - text-to-SQL (LLM generates SQL, executor runs it,
                              LLM synthesizes the answer)
  Rung 4: Agentic RAG       - LangGraph StateGraph + 4 typed tools

All rungs expose the same interface:
    result = run_<rung>(query, model_name=..., db_path=...) -> RungResult
"""
from __future__ import annotations

import json
import operator
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Annotated, Optional, TypedDict

import pandas as pd
from langchain_core.messages import (
    AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from . import tools as tools_mod
from .build_db import get_schema_text

# Common utilities
@dataclass
class RungResult:
    rung: str
    query: str
    response_text: str
    tool_calls: list[dict] = field(default_factory=list)
    sql_generated: Optional[str] = None
    sql_result: Optional[str] = None
    n_llm_calls: int = 0
    error: Optional[str] = None

def _build_model(model_name: str, api_key: str, temperature: float = 0.0):
    """Construct a Gemini chat model with sensible defaults."""
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=api_key,
        temperature=temperature,
        max_output_tokens=2048,
    )

def _extract_text(content) -> str:
    """Coerce an AIMessage.content (str or list[dict]) into a plain string.

    langchain-google-genai 2.x returns content as a list of typed parts when
    Gemini emits thinking blocks or other typed chunks. Concatenate all 'text'
    parts; fall back to str() for unknown shapes.
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                # Typed-content shape: {"type": "text", "text": "..."} etc.
                if "text" in item:
                    parts.append(item["text"])
                # Skip 'thinking' / 'tool_use' / other non-final-text parts
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(p for p in parts if p)
    return str(content)

_RUNG_OUTPUT_FORMAT = """
Always end your response with a JSON block in this exact format (no extra text after it):
```json
{
  "rejection_range_pct": [low, high] or null,
  "recommended_membrane": "name" or null,
  "citations_doi": ["10.xxxx/yyyy", ...],
  "refused": true or false
}
```
Use `null` for fields that don't apply. Set `refused: true` if you don't have data to
answer (e.g., PFAS or membrane not in the dataset).
""".strip()

# Rung 1: Vanilla LLM
_VANILLA_SYSTEM = """
You are a domain expert in nanofiltration and reverse osmosis membranes for PFAS removal.
Answer the user's question concisely and accurately based on your training knowledge.
Do not invent citations; if you do not know a specific value, say so.
""".strip() + "\n\n" + _RUNG_OUTPUT_FORMAT

def run_vanilla(query: str, *, model_name: str, api_key: str) -> RungResult:
    """Rung 1: bare LLM call, no dataset, no tools."""
    model = _build_model(model_name, api_key)
    messages = [SystemMessage(_VANILLA_SYSTEM), HumanMessage(query)]
    try:
        resp = model.invoke(messages)
        return RungResult(
            rung="vanilla",
            query=query,
            response_text=_extract_text(resp.content),
            n_llm_calls=1,
        )
    except Exception as e:
        return RungResult(rung="vanilla", query=query, response_text="",
                          n_llm_calls=1, error=str(e))

# Rung 2: Stuffed-context (entire dataset in the prompt)
def _serialize_dataset_csv(db_path: str, max_rows: Optional[int] = None) -> str:
    """Dump records table as compact CSV text."""
    with sqlite3.connect(db_path) as conn:
        df = pd.read_sql_query("SELECT * FROM records", conn)
    if max_rows:
        df = df.head(max_rows)
    # Trim very long ref strings to keep prompt manageable
    if "ref" in df.columns:
        df["ref"] = df["ref"].astype(str).str.slice(0, 80)
    return df.to_csv(index=False)

_STUFFED_SYSTEM_TEMPLATE = """
You are a domain expert in nanofiltration and reverse osmosis membranes for PFAS removal.
You have access to a curated dataset of PFAS-membrane experimental observations,
provided in CSV form below. Answer the user's question using ONLY this dataset.

OUTPUT RULES (strict):
  1. Do NOT list individual records or copy rows from the dataset. Aggregate them.
  2. For "what is the range" queries, give a single [min, max] pair across ALL matching
     records, not the first few you find.
  3. Cite up to 5 representative DOIs from the matching records (do not list all if
     there are many).
  4. Keep the prose answer under 150 words. Always end with the JSON block.
  5. If the user asks about a PFAS / membrane / technology / contaminant that is NOT
     in this dataset, refuse explicitly rather than fabricate.

DATASET (CSV):
{dataset_csv}

{output_format}
""".strip()

def run_stuffed(query: str, *, model_name: str, api_key: str, db_path: str) -> RungResult:
    """Rung 2: LLM call with the full dataset stuffed into the system prompt."""
    csv_text = _serialize_dataset_csv(db_path)
    system = _STUFFED_SYSTEM_TEMPLATE.format(
        dataset_csv=csv_text, output_format=_RUNG_OUTPUT_FORMAT,
    )
    model = _build_model(model_name, api_key)
    messages = [SystemMessage(system), HumanMessage(query)]
    try:
        resp = model.invoke(messages)
        return RungResult(
            rung="stuffed",
            query=query,
            response_text=_extract_text(resp.content),
            n_llm_calls=1,
        )
    except Exception as e:
        return RungResult(rung="stuffed", query=query, response_text="",
                          n_llm_calls=1, error=str(e))

# Rung 3: Structured RAG (text-to-SQL)
_TEXT_TO_SQL_SYSTEM = """
You translate user questions about PFAS-membrane data into a SINGLE SQLite SQL
query against the schema below. Output rules (strict):

  1. Output ONLY a SQL query wrapped in a ```sql code block. No prose before
     or after.
  2. Use SQLite syntax. Do NOT use PostgreSQL/MySQL features (no ILIKE, no
     RETURNING, no FILTER, no LIMIT 1 OFFSET ... unusual constructs).
  3. SELECT statements only. No INSERT/UPDATE/DELETE/DDL.
  4. Do NOT include SQL comments (no -- ... or /* ... */) inside the query.
  5. Do NOT include multiple statements. No trailing semicolon inside the block.
  6. Use UPPER(...) = UPPER(...) for case-insensitive string comparisons -
     PFAS codes are uppercase ('PFOA', 'PFOS') but be defensive.
  7. Return at most 50 rows (LIMIT 50 unless aggregating).
  8. When asked for ranges, prefer MIN(...) and MAX(...). When asked for
     citations, include the `doi` column.

If the user's question cannot be answered from this schema (e.g., asks about
PFAS or membranes that are not in the database, or about a contaminant other
than PFAS), return exactly:
```sql
SELECT 'NO_QUERY_POSSIBLE' AS reason
```

{schema}
""".strip()

_TEXT_TO_SQL_SYNTH_SYSTEM = """
You are a domain expert in nanofiltration / RO membranes for PFAS removal. You
will receive (a) the user's question, and (b) the rows returned by an executed
SQL query against the PFAS-membrane database.

SYNTHESIS RULES:
  1. If the SQL returned rows that answer the question - even partially - USE
     them. The query was already filtered by the user's constraints; do not
     refuse based on "missing context" that the SQL already addressed.
  2. Trust the SQL result. If the query filtered by membrane_type='Non-commercial'
     and returned 36 membrane names, those 36 ARE the non-commercial membranes;
     you do not need additional confirmation.
  3. For range queries, report the MIN and MAX from the result.
  4. For listing/counting queries, give the count and (if reasonable) the names.
  5. Cite real DOIs from the rows when relevant.
  6. ONLY refuse if (a) the SQL returned 0 rows, (b) the SQL itself errored,
     or (c) the user asked about something genuinely outside this schema
     (e.g., a different contaminant, a different technology).

""".strip() + "\n\n" + _RUNG_OUTPUT_FORMAT

_TEXT_TO_SQL_SYNTH_USER_TEMPLATE = """
User question:
{query}

SQL result rows (CSV):
{sql_result}
""".strip()

_SQL_BLOCK_RE = re.compile(r"```(?:sql|sqlite)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)
_SQL_LINE_COMMENT_RE = re.compile(r"--[^\n]*")
_SQL_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)

def _clean_sql(sql: str) -> str:
    """Strip SQL comments, trailing semicolons, multiple statements, whitespace."""
    if not sql:
        return ""
    s = _SQL_BLOCK_COMMENT_RE.sub(" ", sql)
    s = _SQL_LINE_COMMENT_RE.sub(" ", s)
    # Take only the first statement (split on ; outside quotes - naive but enough)
    if ";" in s:
        s = s.split(";", 1)[0]
    return s.strip()

def _execute_sql(sql: str, db_path: str, max_rows: int = 50) -> tuple[Optional[str], Optional[str]]:
    """Execute read-only SQL. Returns (result_text, error_or_None)."""
    sql_stripped = _clean_sql(sql)
    if not sql_stripped:
        return None, "SQL was empty after cleaning."
    if not sql_stripped.upper().lstrip("(").startswith(("SELECT", "WITH")):
        return None, f"Refused to execute non-SELECT query. Got: {sql_stripped[:120]}"
    forbidden = re.compile(r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|ATTACH|REPLACE)\b", re.I)
    if forbidden.search(sql_stripped):
        return None, "Refused: forbidden keyword detected."
    try:
        with sqlite3.connect(db_path) as conn:
            conn.row_factory = sqlite3.Row
            cur = conn.execute(sql_stripped)
            rows = cur.fetchmany(max_rows)
            if not rows:
                return "(no rows returned)", None
            cols = list(rows[0].keys())
            df = pd.DataFrame([dict(r) for r in rows], columns=cols)
            return df.to_csv(index=False), None
    except sqlite3.Error as e:
        return None, f"SQLite error: {e}"

def run_text_to_sql(query: str, *, model_name: str, api_key: str,
                    db_path: str) -> RungResult:
    """Rung 3: text-to-SQL Structured RAG."""
    schema = get_schema_text(db_path)
    model = _build_model(model_name, api_key)

    # Phase 1: SQL generation
    gen_messages = [
        SystemMessage(_TEXT_TO_SQL_SYSTEM.format(schema=schema)),
        HumanMessage(query),
    ]
    n_calls = 0
    try:
        gen_resp = model.invoke(gen_messages)
        n_calls += 1
    except Exception as e:
        return RungResult(rung="text_to_sql", query=query, response_text="",
                          n_llm_calls=n_calls, error=f"sql_gen_failed: {e}")

    gen_text = _extract_text(gen_resp.content)
    sql_match = _SQL_BLOCK_RE.search(gen_text)
    sql = sql_match.group(1).strip() if sql_match else ""

    # Handle the explicit refusal token
    if "NO_QUERY_POSSIBLE" in sql or not sql:
        sql_result = "(no query was issued)"
        sql_used = sql or "(no SQL generated)"
    else:
        result_text, err = _execute_sql(sql, db_path)
        if err:
            sql_result = f"(SQL execution failed: {err})"
        else:
            sql_result = result_text
        sql_used = sql

    # Phase 2: synthesis (Gemini needs at least one HumanMessage)
    synth_messages = [
        SystemMessage(_TEXT_TO_SQL_SYNTH_SYSTEM),
        HumanMessage(_TEXT_TO_SQL_SYNTH_USER_TEMPLATE.format(
            query=query, sql_result=sql_result,
        )),
    ]
    try:
        synth_resp = model.invoke(synth_messages)
        n_calls += 1
        return RungResult(
            rung="text_to_sql",
            query=query,
            response_text=_extract_text(synth_resp.content),
            sql_generated=sql_used,
            sql_result=sql_result,
            n_llm_calls=n_calls,
        )
    except Exception as e:
        return RungResult(
            rung="text_to_sql", query=query,
            response_text="", sql_generated=sql_used, sql_result=sql_result,
            n_llm_calls=n_calls, error=f"synth_failed: {e}",
        )

# Rung 4: Agentic RAG (LangGraph StateGraph + 4 typed tools)
class AgentState(TypedDict):
    """State carried through the graph. `messages` accumulates with add_messages."""
    messages: Annotated[list[BaseMessage], add_messages]

_AGENT_SYSTEM = """
You are a membrane-selection expert. You have access to a SQL-backed database of
PFAS-membrane records via five typed tools:

  1. filter_records(pfas, membrane, membrane_type, min_rejection, max_rejection,
                    min_pH, max_pH)
     -> match records by any combination of constraints. Returns BOTH the top-50
        rows AND aggregates (min/max/mean rejection, distinct counts) computed
        over ALL matching rows. For "range / min / max" queries, USE THE
        AGGREGATES - the row list may be truncated.
  2. rank_membranes(pfas, by, top_k, min_rejection, membrane_type)
     -> rank membranes for a SINGLE PFAS by a numeric criterion.
        `by` choices: "A", "A_over_B", "A_over_B_times_A", "rejection_pct",
        or "ideal_distance" (Euclidean distance to (1, 1) after min-max
        normalizing log10(A) and log10(A/B), best-record-per-membrane;
        SMALLER = better). Use "ideal_distance" when the user asks for the
        TOP-N membranes "by ideal-point distance" or "ranked by balance of
        permeance and selectivity" - call ONCE per membrane_type, e.g.
        rank_membranes(pfas="PFOA", by="ideal_distance", membrane_type=
        "Commercial", top_k=3) and again with membrane_type=
        "Non-commercial".
  3. get_upper_bound(pfas)
     -> return the fitted permeability-selectivity bound A/B = c * A^(-n).
  4. cite_papers(record_ids)
     -> get atomic (id -> ref + DOI) mapping for IDs returned by the other tools.
  5. find_multi_pfas_membrane(constraints, order_by, top_k, membrane_type)
     -> find membranes whose mean rejection meets ALL given per-PFAS thresholds
        SIMULTANEOUSLY (AND semantics), then rank survivors by water permeance A
        (default), selectivity A_over_B, or the balanced product A_over_B_times_A.
        `constraints` is a list of {"pfas": str, "min_rejection": float}.

PLANNING RULES:
  - Plan a sequence of tool calls to answer the user's question.
  - Do NOT call the same tool twice with identical arguments. If the first call
    returned what you need, proceed to the next step or to the final answer.
  - When the user asks for a single membrane that must clear thresholds on TWO
    OR MORE PFAS simultaneously (e.g. "PFOA > 90% AND PFHxA > 92%"), call
    `find_multi_pfas_membrane` ONCE with all per-PFAS thresholds in one
    `constraints` list - do NOT chain per-PFAS `filter_records` calls and try
    to intersect the result sets yourself. Use `order_by` to express the
    optimization target (maximize permeance -> "A"; maximize selectivity ->
    "A_over_B"; balance both -> "A_over_B_times_A").
  - Always call cite_papers for the record IDs you mention in the final answer.

REFUSAL RULES (refuse rather than fabricate):
  - If filter_records returns 0 matches.
  - If the user asks about a PFAS or membrane that is not in the database.
  - If the user asks about a TECHNOLOGY other than NF or RO membranes
    (e.g., granular activated carbon (GAC), ion exchange, oxidation, electrochemical).
  - If the user asks about a CONTAMINANT other than PFAS (e.g., arsenic, nitrate).
  - If the user asks about operating conditions far outside the dataset
    (e.g., extreme pH < 2 or > 12).
  - If no membrane in the database satisfies the user's STRICT constraints
    simultaneously (e.g., a rejection threshold combined with a permeance
    threshold that no single record meets), ALSO refuse - but you SHOULD still
    provide useful context (the closest-achievable performance and which
    constraint is binding). Set "refused": true in the JSON block AND populate
    the prose with the helpful context.

A refusal is a successful response. Never invent membrane names, DOIs, or values.
"refused": true does NOT mean "I gave no answer" - it means "no entry in the
database satisfies the literal request." You can and should still explain why
in the prose response and cite the closest real records.

""".strip() + "\n\n" + _RUNG_OUTPUT_FORMAT

def _build_agent_graph(model_name: str, api_key: str, tools: list | None = None):
    """Build the compiled LangGraph for rung 4.

    `tools` defaults to the frozen paper toolkit `tools_mod.ALL_TOOLS`. The demo
    path passes `tools_mod.ALL_TOOLS_DEMO` to add the `run_sql` escape hatch.
    """
    tools = tools if tools is not None else tools_mod.ALL_TOOLS
    model = _build_model(model_name, api_key).bind_tools(tools)

    def call_model(state: AgentState) -> dict:
        response = model.invoke(state["messages"])
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        # Continue calling tools as long as the LLM emits tool_calls
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tools"
        return END

    builder = StateGraph(AgentState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=True))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", should_continue, ["tools", END])
    builder.add_edge("tools", "agent")
    return builder.compile()

# Compile once per (model, key) pair and cache; cheap to construct but pointless
# to recompile on every query.
_GRAPH_CACHE: dict[tuple[str, str], object] = {}

def _get_graph(model_name: str, api_key: str):
    key = (model_name, api_key)
    if key not in _GRAPH_CACHE:
        _GRAPH_CACHE[key] = _build_agent_graph(model_name, api_key)
    return _GRAPH_CACHE[key]

def run_agentic(query: str, *, model_name: str, api_key: str, db_path: str,
                recursion_limit: int = 25) -> RungResult:
    """Rung 4: Agentic RAG via LangGraph + 4 typed tools."""
    tools_mod.set_db_path(db_path)
    tools_mod.reset_call_log()
    graph = _get_graph(model_name, api_key)
    messages = [SystemMessage(_AGENT_SYSTEM), HumanMessage(query)]

    n_calls = 0
    try:
        result = graph.invoke(
            {"messages": messages},
            config={"recursion_limit": recursion_limit},
        )
        # Count agent (LLM) turns: every AIMessage in the trace is one LLM call.
        n_calls = sum(1 for m in result["messages"] if isinstance(m, AIMessage))
        final = _extract_text(result["messages"][-1].content)
        # Capture tool calls from audit log
        tool_calls = tools_mod.get_call_log()
        return RungResult(
            rung="agentic",
            query=query,
            response_text=final,
            tool_calls=tool_calls,
            n_llm_calls=n_calls,
        )
    except Exception as e:
        return RungResult(
            rung="agentic", query=query, response_text="",
            tool_calls=tools_mod.get_call_log(),
            n_llm_calls=n_calls, error=str(e),
        )

# DEMO-ONLY variant of the agentic rung.
#
# Adds a sandboxed read-only `run_sql` tool as a LAST-RESORT escape hatch for
# the demo website, so aggregation questions the typed tools can't express
# (e.g. "which membrane has been tested on the most PFAS species") don't dead-
# end. The paper benchmark (run_agentic above) is untouched - same 5 tools,
# same prompt, same graph - so the published numbers stay reproducible.
_AGENT_SYSTEM_DEMO_TOOL = """\
  6. run_sql(query, row_limit)  [LAST RESORT - demo only, NOT in paper benchmark]
     -> run a single read-only SQL SELECT against the `records` table. Use
        ONLY when the typed tools above CANNOT express the question - typical
        cases: GROUP BY aggregations, COUNT(DISTINCT ...) rollups, or
        per-membrane / per-pfas summaries across the whole dataset. Never use
        run_sql for queries the typed tools can already answer; they are
        faster, cheaper, and more auditable. Examples of valid run_sql uses:
          - "which commercial membrane has been tested on the most distinct
             PFAS species?"
             SELECT membrane, COUNT(DISTINCT pfas) AS n_pfas
             FROM records WHERE membrane_type='Commercial'
             GROUP BY membrane ORDER BY n_pfas DESC LIMIT 1;
          - "average rejection of PFOS, grouped by membrane_type":
             SELECT membrane_type, AVG(rejection_pct) FROM records
             WHERE pfas='PFOS' GROUP BY membrane_type;

        Schema (single table `records`):
          id, pfas, membrane, membrane_type, A, B, A_over_B,
          rejection_pct, pH, pressure_psi, init_conc_ngl, doi, ref
"""

def _build_agent_system_demo() -> str:
    """Insert the run_sql section before PLANNING RULES in the base prompt."""
    return _AGENT_SYSTEM.replace(
        "PLANNING RULES:",
        _AGENT_SYSTEM_DEMO_TOOL + "\nPLANNING RULES:",
        1,
    )

_AGENT_SYSTEM_DEMO = _build_agent_system_demo()
_GRAPH_CACHE_DEMO: dict[tuple[str, str], object] = {}

def _get_graph_demo(model_name: str, api_key: str):
    key = (model_name, api_key)
    if key not in _GRAPH_CACHE_DEMO:
        _GRAPH_CACHE_DEMO[key] = _build_agent_graph(
            model_name, api_key, tools=tools_mod.ALL_TOOLS_DEMO,
        )
    return _GRAPH_CACHE_DEMO[key]

def run_agentic_demo(query: str, *, model_name: str, api_key: str, db_path: str,
                     recursion_limit: int = 25) -> RungResult:
    """Demo-only variant of run_agentic with a sandboxed `run_sql` escape hatch.

    Identical contract to run_agentic - returns a RungResult tagged
    rung="agentic" so the existing UI/grading paths don't need to change.
    """
    tools_mod.set_db_path(db_path)
    tools_mod.reset_call_log()
    graph = _get_graph_demo(model_name, api_key)
    messages = [SystemMessage(_AGENT_SYSTEM_DEMO), HumanMessage(query)]

    n_calls = 0
    try:
        result = graph.invoke(
            {"messages": messages},
            config={"recursion_limit": recursion_limit},
        )
        n_calls = sum(1 for m in result["messages"] if isinstance(m, AIMessage))
        final = _extract_text(result["messages"][-1].content)
        tool_calls = tools_mod.get_call_log()
        return RungResult(
            rung="agentic",
            query=query,
            response_text=final,
            tool_calls=tool_calls,
            n_llm_calls=n_calls,
        )
    except Exception as e:
        return RungResult(
            rung="agentic", query=query, response_text="",
            tool_calls=tools_mod.get_call_log(),
            n_llm_calls=n_calls, error=str(e),
        )

# Convenience: run all four rungs on a single query
def run_all(query: str, *, model_name: str, api_key: str, db_path: str) -> dict:
    """Run all four rungs sequentially and return a dict keyed by rung name."""
    return {
        "vanilla":     run_vanilla(query, model_name=model_name, api_key=api_key),
        "stuffed":     run_stuffed(query, model_name=model_name, api_key=api_key, db_path=db_path),
        "text_to_sql": run_text_to_sql(query, model_name=model_name, api_key=api_key, db_path=db_path),
        "agentic":     run_agentic(query, model_name=model_name, api_key=api_key, db_path=db_path),
    }

def visualize_agent_graph(model_name: str = "gemini-3.1-flash-lite",
                          api_key: str = "dummy") -> str:
    """Return a Mermaid diagram of the agentic-RAG graph (for Figure 3A)."""
    graph = _build_agent_graph(model_name, api_key)
    return graph.get_graph().draw_mermaid()
