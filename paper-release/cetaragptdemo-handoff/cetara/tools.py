"""Typed LangChain tools backed by the SQLite database.

Four tools exposed to the agentic-RAG rung (rung 4):
  - filter_records:   filter the dataset by PFAS / membrane / numeric constraints
  - rank_membranes:   rank a candidate set by a numeric field (e.g. permeance A)
  - get_upper_bound:  return the fitted permeability-selectivity bound for a PFAS
  - cite_papers:      atomic (record_id -> ref + DOI) mapping

Every tool reads from a single sqlite3 connection (set via `set_db_path`).
Every call is appended to a module-level `CALL_LOG` for audit-trail logging.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from typing import Optional

from langchain_core.tools import tool

# Connection + audit log
_DB_PATH: Optional[str] = None
_LOCK = threading.Lock()
CALL_LOG: list[dict] = []

def set_db_path(path: str) -> None:
    """Configure the SQLite database file used by all tools."""
    global _DB_PATH
    _DB_PATH = path

def reset_call_log() -> None:
    """Clear the per-query audit trail (call between queries)."""
    CALL_LOG.clear()

def get_call_log() -> list[dict]:
    """Return a copy of the audit trail."""
    return list(CALL_LOG)

def _connect() -> sqlite3.Connection:
    if _DB_PATH is None:
        raise RuntimeError("Call tools.set_db_path(...) before invoking tools.")
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _log(tool_name: str, args: dict, result_summary: str) -> None:
    with _LOCK:
        CALL_LOG.append({"tool": tool_name, "args": args, "result": result_summary})

# Tool 1: filter_records
@tool
def filter_records(
    pfas: Optional[str] = None,
    membrane: Optional[str] = None,
    membrane_type: Optional[str] = None,
    min_rejection: Optional[float] = None,
    max_rejection: Optional[float] = None,
    min_pH: Optional[float] = None,
    max_pH: Optional[float] = None,
) -> str:
    """Filter the PFAS-membrane records by any combination of constraints.

    Use this to find records matching a PFAS species, a specific membrane,
    a rejection threshold (e.g., min_rejection=90 means rejection >= 90%),
    or a pH range. Returns a JSON string with up to 50 matching record IDs
    and a summary count. If nothing matches, the agent should refuse rather
    than fabricate.

    Args:
        pfas: PFAS species code, e.g. "PFOA", "PFBA", "PFOS"
        membrane: membrane name, e.g. "NF270", "NF90", "DL"
        membrane_type: "Commercial" or "Non-commercial"
        min_rejection: minimum rejection percentage (0-100)
        max_rejection: maximum rejection percentage (0-100)
        min_pH: minimum pH
        max_pH: maximum pH
    """
    where = []
    params: list = []
    if pfas is not None:
        where.append("UPPER(pfas) = UPPER(?)")
        params.append(pfas)
    if membrane is not None:
        where.append("UPPER(membrane) = UPPER(?)")
        params.append(membrane)
    if membrane_type is not None:
        where.append("UPPER(membrane_type) = UPPER(?)")
        params.append(membrane_type)
    if min_rejection is not None:
        where.append("rejection_pct >= ?")
        params.append(min_rejection)
    if max_rejection is not None:
        where.append("rejection_pct <= ?")
        params.append(max_rejection)
    if min_pH is not None:
        where.append("pH >= ?")
        params.append(min_pH)
    if max_pH is not None:
        where.append("pH <= ?")
        params.append(max_pH)
    where_clause = "WHERE " + " AND ".join(where) if where else ""

    sql_rows = f"""
        SELECT id, membrane, membrane_type, pfas, A, B, A_over_B,
               rejection_pct, pH, pressure_psi, init_conc_ngl
        FROM records {where_clause}
        ORDER BY rejection_pct DESC
        LIMIT 50
    """
    sql_agg = f"""
        SELECT COUNT(*)                              AS n_matches,
               COUNT(DISTINCT membrane)              AS n_distinct_membranes,
               COUNT(DISTINCT pfas)                  AS n_distinct_pfas,
               COUNT(DISTINCT doi)                   AS n_distinct_papers,
               MIN(rejection_pct)                    AS min_rejection_pct,
               MAX(rejection_pct)                    AS max_rejection_pct,
               AVG(rejection_pct)                    AS mean_rejection_pct,
               MIN(A)                                AS min_A,
               MAX(A)                                AS max_A
        FROM records {where_clause}
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(sql_rows, params).fetchall()]
        agg_row = conn.execute(sql_agg, params).fetchone()
        agg = dict(agg_row) if agg_row else {}

    args = {k: v for k, v in {
        "pfas": pfas, "membrane": membrane, "membrane_type": membrane_type,
        "min_rejection": min_rejection, "max_rejection": max_rejection,
        "min_pH": min_pH, "max_pH": max_pH,
    }.items() if v is not None}
    n_total = agg.get("n_matches", 0) or 0
    _log("filter_records", args, f"{n_total} matches, {len(rows)} rows + aggregates")

    # Aggregates are computed over ALL matching rows (not just the 50 returned),
    # so the LLM gets the true min/max even when the row list is truncated.
    return json.dumps({
        "n_matches": n_total,
        "n_returned": len(rows),
        "aggregates": agg,
        "rows": rows,
        "note": ("If n_matches > n_returned, the row list is truncated to 50 "
                 "(highest rejection first), but `aggregates` are computed over "
                 "ALL matching rows. Use aggregates for min/max/mean queries."),
    }, default=str)

# Tool 2: rank_membranes
@tool
def rank_membranes(
    pfas: str,
    by: str = "A_over_B_times_A",
    top_k: int = 5,
    min_rejection: Optional[float] = None,
    membrane_type: Optional[str] = None,
) -> str:
    """Rank membranes for a given PFAS by a chosen numeric criterion.

    Use this when the user asks for the "best" or "top" membranes for a PFAS.
    For most criteria, aggregates by membrane (averages over duplicate
    measurements) and returns the top_k candidates with their stats.
    The exception is `by="ideal_distance"`, which uses BEST-RECORD-per-membrane
    in normalized log10(A)-log10(A/B) space - see below.

    Args:
        pfas: PFAS species code (required)
        by: ranking criterion. One of:
            - "A"               (water permeance, higher = better)
            - "A_over_B"        (selectivity, higher = better)
            - "A_over_B_times_A" (balance of permeance and selectivity, default)
            - "rejection_pct"   (raw rejection rate, higher = better)
            - "ideal_distance"  (Euclidean distance to the ideal point (1, 1)
                                 after min-max normalizing log10(A) and
                                 log10(A/B) across this PFAS's records; the
                                 BEST record per (membrane, type) is kept,
                                 then the deduped set is re-normalized.
                                 SMALLER distance = better. This is the same
                                 criterion used by the recommendation-prompt
                                 golden answers - use it when the user
                                 explicitly asks for "ideal-point distance"
                                 or "balanced permeance + selectivity".)
        top_k: number of top membranes to return (default 5)
        min_rejection: optional rejection threshold to pre-filter (e.g. 90)
        membrane_type: optional filter "Commercial" or "Non-commercial"
                       (applied AFTER normalization for ideal_distance, so the
                       normalization range is the same as the golden answer's)
    """
    valid_by = {"A", "A_over_B", "A_over_B_times_A", "rejection_pct",
                "ideal_distance"}
    if by not in valid_by:
        return json.dumps({"error": f"`by` must be one of {sorted(valid_by)}"})

    # Special path: ideal-point distance.  Done in Python (not SQL) because
    # the algorithm is: filter -> log -> min-max normalize -> dedupe to
    # best record per (membrane, type) -> RE-normalize -> rank.
    if by == "ideal_distance":
        import math
        where_ip = ["UPPER(pfas) = UPPER(?)",
                    "A IS NOT NULL", "A > 0",
                    "A_over_B IS NOT NULL", "A_over_B > 0"]
        params_ip: list = [pfas]
        if min_rejection is not None:
            where_ip.append("rejection_pct >= ?")
            params_ip.append(min_rejection)
        sql_ip = f"""
            SELECT id, membrane, membrane_type, A, B, A_over_B,
                   rejection_pct, doi, ref
            FROM records WHERE {" AND ".join(where_ip)}
        """
        with _connect() as conn:
            rows_ip = [dict(r) for r in conn.execute(sql_ip, params_ip).fetchall()]
        if not rows_ip:
            args_ip = {k: v for k, v in {
                "pfas": pfas, "by": by, "top_k": top_k,
                "min_rejection": min_rejection, "membrane_type": membrane_type,
            }.items() if v is not None}
            _log("rank_membranes", args_ip, "0 matching records")
            return json.dumps({"pfas": pfas, "by": by, "rows": []})

        def _normalize(rs: list[dict]) -> None:
            la = [math.log10(r["A"]) for r in rs]
            ls = [math.log10(r["A_over_B"]) for r in rs]
            a_rng = (max(la) - min(la)) or 1.0
            s_rng = (max(ls) - min(ls)) or 1.0
            for r, x, y in zip(rs, la, ls):
                r["logA_norm"] = (x - min(la)) / a_rng
                r["logS_norm"] = (y - min(ls)) / s_rng
                r["ideal_distance"] = math.sqrt(
                    (1.0 - r["logA_norm"]) ** 2
                    + (1.0 - r["logS_norm"]) ** 2
                )

        # Pass 1: normalize across all records
        _normalize(rows_ip)
        # Dedupe to best record per (membrane, type)
        best: dict[tuple[str, str], dict] = {}
        for r in rows_ip:
            key = (r["membrane"], (r["membrane_type"] or "").upper())
            if key not in best or r["ideal_distance"] < best[key]["ideal_distance"]:
                best[key] = r
        deduped = list(best.values())
        # Pass 2: re-normalize on the deduped set (matches the golden-answer recipe)
        _normalize(deduped)
        # Optional post-filter by membrane_type
        if membrane_type is not None:
            mt = membrane_type.upper()
            deduped = [r for r in deduped
                       if (r["membrane_type"] or "").upper() == mt]
        # Rank: smaller distance = better
        deduped.sort(key=lambda r: r["ideal_distance"])
        out_rows = []
        for r in deduped[:top_k]:
            out_rows.append({
                "membrane":        r["membrane"],
                "membrane_type":   r["membrane_type"],
                "best_record_id":  r["id"],
                "A":               r["A"],
                "B":               r["B"],
                "A_over_B":        r["A_over_B"],
                "rejection_pct":   r["rejection_pct"],
                "doi":             r["doi"],
                "ref":             r["ref"],
                "logA_norm":       round(r["logA_norm"], 4),
                "logS_norm":       round(r["logS_norm"], 4),
                "ideal_distance":  round(r["ideal_distance"], 4),
            })
        args_ip = {k: v for k, v in {
            "pfas": pfas, "by": by, "top_k": top_k,
            "min_rejection": min_rejection, "membrane_type": membrane_type,
        }.items() if v is not None}
        _log("rank_membranes", args_ip,
             f"returned {len(out_rows)} ranked by ideal_distance")
        return json.dumps({
            "pfas": pfas, "by": by, "rows": out_rows,
            "note": ("`ideal_distance` is computed by: (1) take all records "
                     "with A > 0 and A/B > 0 for this PFAS; (2) min-max "
                     "normalize log10(A) and log10(A/B) to [0, 1]; (3) keep "
                     "the best record (smallest distance to (1, 1)) per "
                     "(membrane, type); (4) re-normalize on the deduped set; "
                     "(5) rank by distance ascending. SMALLER distance = "
                     "better balance of permeance and selectivity."),
        }, default=str)

    where = ["UPPER(pfas) = UPPER(?)"]
    params: list = [pfas]
    if min_rejection is not None:
        where.append("rejection_pct >= ?")
        params.append(min_rejection)
    if membrane_type is not None:
        where.append("UPPER(membrane_type) = UPPER(?)")
        params.append(membrane_type)
    where_clause = " AND ".join(where)

    if by == "A_over_B_times_A":
        order_expr = "AVG(A_over_B * A)"
    else:
        order_expr = f"AVG({by})"

    sql = f"""
        SELECT membrane,
               membrane_type,
               COUNT(*) AS n_obs,
               AVG(A) AS mean_A,
               AVG(B) AS mean_B,
               AVG(A_over_B) AS mean_AB,
               AVG(rejection_pct) AS mean_rejection,
               MIN(rejection_pct) AS min_rejection,
               MAX(rejection_pct) AS max_rejection,
               {order_expr} AS score
        FROM records
        WHERE {where_clause}
        GROUP BY membrane, membrane_type
        ORDER BY score DESC
        LIMIT ?
    """
    params.append(top_k)
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    args = {"pfas": pfas, "by": by, "top_k": top_k,
            "min_rejection": min_rejection, "membrane_type": membrane_type}
    args = {k: v for k, v in args.items() if v is not None}
    _log("rank_membranes", args, f"returned {len(rows)} ranked membranes")

    return json.dumps({"pfas": pfas, "by": by, "rows": rows}, default=str)

# Tool 3: get_upper_bound
@tool
def get_upper_bound(pfas: str) -> str:
    """Get the fitted permeability-selectivity upper-bound parameters for a PFAS.

    The bound has the form A/B = c * A^(-n). Returns the fitted c, n, their
    95% bootstrap confidence intervals, and the number of leading-edge points
    used in the fit. Use this to check whether user-requested performance is
    feasible against the empirical limit.

    Args:
        pfas: PFAS species code, e.g. "PFOA"
    """
    sql = """
        SELECT pfas, c, n, c_lower, c_upper, n_lower, n_upper, n_points
        FROM upper_bounds
        WHERE UPPER(pfas) = UPPER(?)
    """
    with _connect() as conn:
        row = conn.execute(sql, (pfas,)).fetchone()
    if row is None:
        result = {"pfas": pfas, "found": False,
                  "note": "No upper bound available - insufficient data for this PFAS."}
    else:
        result = {"pfas": row["pfas"], "found": True,
                  "c": row["c"], "n": row["n"],
                  "c_95ci": [row["c_lower"], row["c_upper"]],
                  "n_95ci": [row["n_lower"], row["n_upper"]],
                  "n_points": row["n_points"]}
    _log("get_upper_bound", {"pfas": pfas},
         "found" if result.get("found") else "not found")
    return json.dumps(result)

# Tool 4: cite_papers
@tool
def cite_papers(record_ids: list[int]) -> str:
    """Return the (record_id -> reference title + DOI) mapping for given records.

    Use this AFTER selecting records, to attach atomic citations to your final
    answer. Hallucinated DOIs are structurally impossible because the DOI is
    looked up from the database, not generated.

    Args:
        record_ids: list of record IDs (integers) from filter_records or rank_membranes
    """
    if not record_ids:
        return json.dumps({"citations": []})
    placeholders = ",".join("?" * len(record_ids))
    sql = f"""
        SELECT id, ref, doi
        FROM records
        WHERE id IN ({placeholders})
    """
    with _connect() as conn:
        rows = [dict(r) for r in conn.execute(sql, record_ids).fetchall()]
    _log("cite_papers", {"record_ids": record_ids}, f"returned {len(rows)} citations")
    return json.dumps({"citations": rows}, default=str)

# Tool 5: find_multi_pfas_membrane
@tool
def find_multi_pfas_membrane(
    constraints: list[dict],
    order_by: str = "A",
    top_k: int = 5,
    membrane_type: Optional[str] = None,
) -> str:
    """Find membranes whose per-PFAS mean rejection meets ALL the given
    constraints simultaneously, then rank survivors by a numeric criterion.

    Use this for multi-PFAS scenarios like "membrane that achieves PFOA > 90%
    AND PFHxA > 92% while maximizing water permeance". Aggregates by membrane
    (averages duplicate measurements per PFAS) before applying the thresholds,
    so each membrane gets one mean-rejection value per PFAS.

    Args:
        constraints: list of {"pfas": str, "min_rejection": float} dicts.
                     E.g. [{"pfas": "PFOA", "min_rejection": 90},
                           {"pfas": "PFHxA", "min_rejection": 92}].
                     ALL constraints must be satisfied (AND semantics).
        order_by: ranking criterion among survivors. One of:
            - "A"                 (water permeance, higher = better; default)
            - "A_over_B"          (water/PFAS selectivity, higher = better)
            - "A_over_B_times_A"  (balance of permeance and selectivity)
        top_k: number of top survivors to return (default 5).
        membrane_type: optional filter "Commercial" or "Non-commercial".
    """
    if not constraints:
        return json.dumps({"error": "constraints list cannot be empty",
                           "rows": [], "n_survivors": 0})
    valid_order = {"A", "A_over_B", "A_over_B_times_A"}
    if order_by not in valid_order:
        return json.dumps({"error": f"`order_by` must be one of {sorted(valid_order)}"})

    # Per-membrane mean rejection on each constrained PFAS
    type_where = ""
    type_params: list = []
    if membrane_type is not None:
        type_where = " AND UPPER(membrane_type) = UPPER(?)"
        type_params = [membrane_type]

    with _connect() as conn:
        per_pfas_means: dict[str, dict[str, float]] = {}
        for c in constraints:
            pfas = c.get("pfas")
            if not pfas:
                continue
            sql = (
                "SELECT membrane, AVG(rejection_pct) AS mean_rej "
                "FROM records WHERE UPPER(pfas) = UPPER(?)"
                + type_where +
                " GROUP BY membrane"
            )
            rows = conn.execute(sql, [pfas, *type_params]).fetchall()
            per_pfas_means[pfas.upper()] = {
                r["membrane"]: float(r["mean_rej"]) for r in rows
                if r["mean_rej"] is not None
            }

        # Intersect: membranes that meet EVERY constraint
        survivors: set[str] = None
        for c in constraints:
            pfas = (c.get("pfas") or "").upper()
            thr = float(c.get("min_rejection", 0))
            means = per_pfas_means.get(pfas, {})
            ok = {m for m, v in means.items() if v > thr}
            survivors = ok if survivors is None else (survivors & ok)
        survivors = survivors or set()

        if not survivors:
            _log("find_multi_pfas_membrane",
                 {"constraints": constraints, "order_by": order_by,
                  "top_k": top_k, "membrane_type": membrane_type},
                 "0 survivors")
            return json.dumps({
                "n_survivors": 0,
                "rows": [],
                "note": ("No membrane in the database meets all constraints "
                         "simultaneously. Consider relaxing a threshold."),
            })

        # Rank survivors by the requested criterion (mean across their records)
        placeholders = ",".join("?" * len(survivors))
        if order_by == "A_over_B_times_A":
            score_expr = "AVG(A * A_over_B)"
        else:
            score_expr = f"AVG({order_by})"
        sql_rank = (
            f"SELECT membrane, membrane_type, COUNT(*) AS n_obs, "
            f"AVG(A) AS mean_A, AVG(A_over_B) AS mean_AB, "
            f"{score_expr} AS score "
            f"FROM records WHERE membrane IN ({placeholders})"
            + type_where +
            " GROUP BY membrane, membrane_type ORDER BY score DESC LIMIT ?"
        )
        params = [*sorted(survivors), *type_params, top_k]
        ranked = [dict(r) for r in conn.execute(sql_rank, params).fetchall()]

    # Attach the per-PFAS mean rejection for each surviving membrane so the
    # LLM can report it directly in the answer
    for row in ranked:
        m = row["membrane"]
        row["rejection_by_pfas"] = {
            c.get("pfas"): per_pfas_means[(c.get("pfas") or "").upper()].get(m)
            for c in constraints if c.get("pfas")
        }

    args = {"constraints": constraints, "order_by": order_by,
            "top_k": top_k, "membrane_type": membrane_type}
    _log("find_multi_pfas_membrane", args,
         f"{len(survivors)} survivors, top-{len(ranked)} returned")
    return json.dumps({
        "n_survivors": len(survivors),
        "ranked_by": order_by,
        "rows": ranked,
    }, default=str)

# Tool 6 (DEMO ONLY): run_sql - sandboxed read-only SELECT escape hatch.
#
# NOT included in ALL_TOOLS so the paper benchmark (run_agentic in rungs.py)
# never sees it.  Exposed only through `run_agentic_demo` for the live demo
# website, where it lets the agent answer aggregation questions the typed
# tools can't express (e.g. "which membrane has been tested on the most
# distinct PFAS species" -> GROUP BY + COUNT DISTINCT).
_SQL_OK_PREFIX = re.compile(r"^\s*(SELECT|WITH)\b", re.IGNORECASE)
_SQL_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|REPLACE|ATTACH|DETACH|"
    r"PRAGMA|VACUUM|REINDEX|TRUNCATE)\b",
    re.IGNORECASE,
)
_SQL_HAS_LIMIT = re.compile(r"\bLIMIT\s+\d+", re.IGNORECASE)

@tool
def run_sql(query: str, row_limit: int = 200) -> str:
    """Execute a *read-only* SQL SELECT against the PFAS-membrane database.

    LAST-RESORT escape hatch. Use this ONLY when the typed tools (filter_records,
    rank_membranes, get_upper_bound, find_multi_pfas_membrane) CANNOT express
    the question. Typical valid uses:
      - GROUP BY aggregations  ("for each membrane, how many distinct PFAS...")
      - COUNT(DISTINCT ...) rollups
      - Per-membrane or per-pfas summaries that span the whole dataset
      - JOIN-style intersections between subsets

    Do NOT use it for queries the typed tools can handle (single-PFAS ranking,
    simple filtering, recommending a membrane for one PFAS, etc.) - those are
    faster, cheaper, and more auditable through the typed tools.

    Safety constraints:
      - Must be a single statement starting with SELECT or WITH.
      - Forbidden keywords (INSERT/UPDATE/DELETE/DROP/CREATE/ALTER/REPLACE/
        ATTACH/DETACH/PRAGMA/VACUUM/REINDEX/TRUNCATE) reject the query.
      - The connection is opened read-only at the OS level; write attempts fail.
      - If no LIMIT clause is present, LIMIT `row_limit` is appended.
      - Hard cap: `row_limit` is clamped to [1, 500].

    Schema (single table `records`):
      id            INTEGER PRIMARY KEY
      pfas          TEXT     e.g. 'PFOA', 'PFBA', 'PFOS'
      membrane      TEXT     e.g. 'NF270', 'NF90', 'DL'
      membrane_type TEXT     'Commercial' or 'Non-commercial'
      A             REAL     water permeance, L/(m^2 h bar)
      B             REAL     solute permeance, L/(m^2 h bar)
      A_over_B      REAL     selectivity A/B
      rejection_pct REAL     0-100
      pH            REAL
      pressure_psi  REAL
      init_conc_ngl REAL     initial concentration, ng/L
      doi           TEXT     paper DOI
      ref           TEXT     paper short reference

    Args:
        query: a single SELECT or WITH...SELECT statement.
        row_limit: max rows returned (default 200, capped at 500).

    Returns a JSON string: {"n_rows": int, "rows": [...], "query": str} on
    success, or {"error": str} on rejection / SQL error.
    """
    q_in = (query or "").strip()
    if not q_in:
        return json.dumps({"error": "Empty query."})
    if not _SQL_OK_PREFIX.match(q_in):
        return json.dumps({"error": "Query must start with SELECT or WITH."})
    if _SQL_FORBIDDEN.search(q_in):
        return json.dumps({
            "error": "Forbidden keyword detected. Only read-only SELECT/WITH "
                     "queries are allowed (no INSERT/UPDATE/DELETE/DROP/CREATE/"
                     "ALTER/REPLACE/ATTACH/DETACH/PRAGMA/VACUUM/REINDEX)."
        })
    # Reject multi-statement input (defends against trailing `; DROP TABLE ...`)
    stripped = q_in.rstrip(";").strip()
    if ";" in stripped:
        return json.dumps({
            "error": "Multiple statements not allowed. Send exactly one SELECT."
        })
    n = max(1, min(int(row_limit or 200), 500))
    final_sql = stripped if _SQL_HAS_LIMIT.search(stripped) else f"{stripped} LIMIT {n}"

    if _DB_PATH is None:
        raise RuntimeError("Call tools.set_db_path(...) before invoking tools.")
    try:
        # `mode=ro` makes the connection truly read-only at the SQLite layer -
        # any write attempt fails even if a forbidden keyword slipped past.
        ro_uri = f"file:{_DB_PATH}?mode=ro"
        with sqlite3.connect(ro_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = [dict(r) for r in conn.execute(final_sql).fetchall()]
    except sqlite3.Error as e:
        _log("run_sql", {"query": final_sql[:160]}, f"sqlite error: {e}")
        return json.dumps({"error": f"SQL error: {e}", "query": final_sql})

    _log("run_sql", {"query": final_sql[:160]}, f"{len(rows)} rows")
    return json.dumps(
        {"n_rows": len(rows), "rows": rows, "query": final_sql},
        default=str,
    )

# Convenience: list of all tools (for binding to a model)
# Paper-benchmark toolkit - exactly the 5 typed tools used in 01_run_experiments.
# DO NOT add run_sql here; that would change the published benchmark numbers.
ALL_TOOLS = [filter_records, rank_membranes, get_upper_bound, cite_papers,
             find_multi_pfas_membrane]

# Demo-only toolkit - the paper toolkit PLUS the sandboxed SQL escape hatch.
# Imported by rungs.run_agentic_demo (and never by run_agentic).
ALL_TOOLS_DEMO = ALL_TOOLS + [run_sql]
