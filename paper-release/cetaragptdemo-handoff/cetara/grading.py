"""Multi-metric grader for benchmark responses.

Each rung returns a free-text response. We extract a structured `Answer` from
the text (rejection range, recommended membrane, citations, refusal flag) and
score it against the ground truth pulled from the SQLite database.

Metrics:
  - jaccard_range:        overlap of predicted [low, high] vs. ground-truth
  - citation_accuracy:    fraction of cited DOIs that are real (in DB) and relevant
  - hallucination_flag:   True if the response mentions a membrane/PFAS not in DB
  - refusal_correct:      True iff (refused == ground_truth_should_refuse)
  - exact_match_membrane: for recommendation queries, did the recommendation match a top-k?
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Optional

# Parsing the LLM's free-text response into a structured Answer
@dataclass
class Answer:
    raw_text: str
    rejection_range: Optional[tuple[float, float]] = None  # (low_pct, high_pct)
    recommended_membrane: Optional[str] = None
    citations: list[str] = field(default_factory=list)  # list of DOI URLs/strings
    refused: bool = False

_RANGE_RE = re.compile(
    r"(?:range|between|from)?\s*"
    r"(\d{1,3}(?:\.\d+)?)\s*%?\s*"
    r"(?:[-–-to]+|and|,)\s*"
    r"(\d{1,3}(?:\.\d+)?)\s*%",
    re.IGNORECASE,
)
# Look for DOI patterns: 10.xxxx/yyyy or full URLs.
# Exclude markdown-format characters (* _ ` ~), HTML/angle brackets (< >),
# braces, and the standard quote/punctuation set from the capture body.
# A real DOI character set (per Crossref / DOI handbook) is essentially
# "printable ASCII excluding the few separators we list", so being strict
# here only filters formatting noise.
_DOI_RE = re.compile(
    r"(?:https?://(?:dx\.)?doi\.org/)?(10\.\d{4,9}/[^\s\"',;\)\]\}\>\<\*_`~]+)",
    re.IGNORECASE,
)
_REFUSAL_PHRASES = (
    "i don't have data", "i do not have data", "no data available",
    "not in the dataset", "outside the dataset", "no records",
    "cannot recommend", "i can't recommend", "unable to recommend",
    "no matching", "no information available", "i am unable to",
)
# Find a ```json ... ``` block (the structured-output convention we instructed
# every rung to emit at the end of its response)
_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)
# Fallback: a bare {...} block at the end of the response
_TRAILING_JSON_RE = re.compile(r"(\{[^{}]*\"rejection_range_pct\"[^{}]*\})", re.DOTALL)

def _try_parse_json_answer(text: str) -> Optional[dict]:
    """Try to extract the structured ```json {...} ``` block we instructed
    every rung to emit. Returns the parsed dict or None."""
    for pat in (_JSON_BLOCK_RE, _TRAILING_JSON_RE):
        m = pat.search(text)
        if not m:
            continue
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None

def parse_response(text: str) -> Answer:
    """Parse an LLM response into a structured Answer.

    Strategy: prefer the model's own structured output (```json {...} ``` block
    that we instructed every rung to emit). Fall back to free-text regex when
    the JSON block is missing or malformed.
    """
    ans = Answer(raw_text=text)
    obj = _try_parse_json_answer(text)

    if obj is not None:
        # ----- Structured path -----
        rng = obj.get("rejection_range_pct")
        if isinstance(rng, (list, tuple)) and len(rng) == 2:
            try:
                low, high = float(rng[0]), float(rng[1])
                if 0 <= low <= 100 and 0 <= high <= 100 and low <= high:
                    ans.rejection_range = (low, high)
            except (TypeError, ValueError):
                pass

        rec = obj.get("recommended_membrane")
        if isinstance(rec, str) and rec.strip():
            ans.recommended_membrane = rec.strip()

        cites = obj.get("citations_doi") or []
        if isinstance(cites, list):
            seen = set()
            for c in cites:
                if not isinstance(c, str):
                    continue
                # Normalize: strip URL prefix; keep just the 10.xxxx/yyyy form
                m = _DOI_RE.search(c)
                doi = m.group(1).rstrip(".,;)\"' *_`~>") if m else c.strip()
                if doi and doi not in seen:
                    seen.add(doi)
                    ans.citations.append(doi)

        refused = obj.get("refused")
        if isinstance(refused, bool):
            ans.refused = refused
    else:
        # ----- Free-text fallback -----
        for m in _RANGE_RE.finditer(text):
            low = float(m.group(1))
            high = float(m.group(2))
            if 0 <= low <= 100 and 0 <= high <= 100 and low <= high:
                ans.rejection_range = (low, high)
                break
        rec_match = re.search(
            r"\b(?:recommend(?:ed)?|select(?:ed)?|best|top choice)\s*(?:is|:)?\s*"
            r"['\"\*]*([A-Z][\w\-./()]{1,30})['\"\*]*",
            text,
        )
        if rec_match:
            ans.recommended_membrane = rec_match.group(1).strip("*'\"")

    # Always also collect any DOIs mentioned in the free text - they
    # complement the JSON-block citations and catch parser misses
    seen = {d.lower() for d in ans.citations}
    for m in _DOI_RE.finditer(text):
        doi = m.group(1).rstrip(".,;)\"' *_`~>")
        if doi.lower() not in seen:
            seen.add(doi.lower())
            ans.citations.append(doi)

    # Always also check refusal phrases in free text (keep the JSON value
    # if it was set, otherwise fall back to phrase detection)
    if obj is None or not isinstance(obj.get("refused"), bool):
        text_lower = text.lower()
        ans.refused = any(p in text_lower for p in _REFUSAL_PHRASES)

    return ans

# Ground-truth lookups (from the SQLite database)
def get_ground_truth_range(
    db_path: str, pfas: str, membrane: str
) -> Optional[tuple[float, float]]:
    """Return (min, max) rejection percentage for a (pfas, membrane) pair, or None."""
    sql = """
        SELECT MIN(rejection_pct) AS lo, MAX(rejection_pct) AS hi
        FROM records
        WHERE UPPER(pfas) = UPPER(?) AND UPPER(membrane) = UPPER(?)
    """
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(sql, (pfas, membrane)).fetchone()
    if row is None or row[0] is None:
        return None
    return (float(row[0]), float(row[1]))

def get_dois_for_pair(db_path: str, pfas: str, membrane: str) -> list[str]:
    """Return DOIs of all records for a (pfas, membrane) pair."""
    sql = """
        SELECT DISTINCT doi FROM records
        WHERE UPPER(pfas) = UPPER(?) AND UPPER(membrane) = UPPER(?)
          AND doi IS NOT NULL
    """
    with sqlite3.connect(db_path) as conn:
        return [r[0] for r in conn.execute(sql, (pfas, membrane)).fetchall()]

def get_known_pfas(db_path: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {r[0].upper() for r in conn.execute("SELECT DISTINCT pfas FROM records")}

def get_known_membranes(db_path: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {r[0].upper() for r in conn.execute("SELECT DISTINCT membrane FROM records")}

def get_known_dois(db_path: str) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT DISTINCT doi FROM records WHERE doi IS NOT NULL")
    out = set()
    for (d,) in rows:
        m = _DOI_RE.search(d) if d else None
        if m:
            out.add(m.group(1).lower())
    return out

# Metric implementations
def jaccard_range(predicted: Optional[tuple[float, float]],
                  truth: Optional[tuple[float, float]]) -> Optional[float]:
    """Jaccard / IoU of two intervals. None if either side missing."""
    if predicted is None or truth is None:
        return None
    a1, a2 = predicted
    b1, b2 = truth
    inter = max(0.0, min(a2, b2) - max(a1, b1))
    union = max(a2, b2) - min(a1, b1)
    if union <= 0:
        # Degenerate intervals (single point); treat as exact match if equal
        return 1.0 if predicted == truth else 0.0
    return inter / union

def citation_accuracy(predicted_dois: list[str],
                      relevant_dois: list[str],
                      known_dois: set[str]) -> dict:
    """Score how well the cited DOIs match what's actually in the database.

    Returns:
        {
            "n_cited": ...,
            "n_relevant_hit": ...,
            "n_hallucinated": ...,  # cited DOIs NOT in the DB at all
            "precision_relevant": fraction of cited that are relevant
            "recall_relevant":    fraction of relevant that were cited
        }
    """
    cited_norm = {d.lower().rstrip(".,;)\"' *_`~>") for d in predicted_dois}
    relevant_norm = {d.lower() for d in (_DOI_RE.search(x).group(1) if _DOI_RE.search(x or "") else "" for x in relevant_dois) if d}
    relevant_norm.discard("")
    known_norm = {d.lower() for d in known_dois}

    n_cited = len(cited_norm)
    n_hallucinated = len(cited_norm - known_norm)
    n_hit = len(cited_norm & relevant_norm)
    precision = n_hit / n_cited if n_cited else None
    recall = n_hit / len(relevant_norm) if relevant_norm else None
    return {
        "n_cited": n_cited,
        "n_relevant_hit": n_hit,
        "n_hallucinated": n_hallucinated,
        "precision_relevant": precision,
        "recall_relevant": recall,
    }

def _split_membrane_field(s: str) -> list[str]:
    """Split a free-text `recommended_membrane` value into individual candidate
    membrane names.

    Handles common LLM output patterns:
      - 'NF270'                          -> ['NF270']
      - 'NF270, NF90'                    -> ['NF270', 'NF90']
      - 'NF270 and NF90'                 -> ['NF270', 'NF90']
      - 'ETOH-4 (Non-commercial), NF90 (Commercial)' -> ['ETOH-4', 'NF90']
      - 'NF270; NF90'                    -> ['NF270', 'NF90']
      - 'DL(PDADMAC/PSS)1'               -> ['DL(PDADMAC/PSS)1']  (composition preserved)
      - 'DL(PDADMAC/PSS)1, DL(PDADMAC/PSS)3' -> ['DL(PDADMAC/PSS)1', 'DL(PDADMAC/PSS)3']

    Strips ONLY trailing role-tag parentheticals like '(Commercial)' or
    '(Non-commercial)' - those that are detached from a preceding word by
    whitespace. Inline parens that are part of the membrane name itself
    (e.g. 'DL(PDADMAC/PSS)1') are preserved. Splits on ',', ';', '+', '&',
    or ' and ' (NOT '/', which is used inside polymer-composition notation
    like PDADMAC/PSS).
    """
    if not s:
        return []
    # Strip ONLY whitespace-detached parentheticals (role tags), not inline ones
    s_clean = re.sub(r"\s+\([^)]*\)", "", s)
    # Split on list separators that don't conflict with chemistry notation
    parts = re.split(r"\s*(?:,|;|\+|&|\sand\s)\s*", s_clean, flags=re.IGNORECASE)
    return [p.strip(" \t\"'*") for p in parts if p.strip(" \t\"'*")]

def _is_known_membrane(name: str, known_membranes: set[str]) -> bool:
    """Case-insensitive membrane lookup with a hyphen-stripping fallback so
    'NF-270' matches 'NF270'."""
    if not name:
        return False
    upper = name.upper()
    if upper in known_membranes:
        return True
    stripped = upper.replace("-", "")
    return any(stripped == m.replace("-", "") for m in known_membranes)

# Generic descriptors that show up when the model is describing a CLASS of
# membrane rather than naming a specific product (e.g. "polyamide TFC
# membranes", "non-commercial surface-modified membranes"). Used by
# `_is_class_description` to skip the membrane-hallucination check when the
# response is a research direction, not a product claim.
_CLASS_DESC_TOKENS: frozenset[str] = frozenset({
    # Membrane terminology
    "membrane", "membranes",
    # Polymer chemistry / structure
    "polyamide", "pa", "polysulfone", "polyethersulfone", "pes", "psf",
    "polypiperazine", "thinfilm", "thin", "film", "thin-film",
    "composite", "tfc", "tfn", "nanocomposite", "polyelectrolyte",
    "polymeric", "polymer",
    # Type / source
    "commercial", "non-commercial", "noncommercial",
    "research", "research-grade", "lab", "lab-scale", "labscale",
    "novel", "advanced", "next-generation",
    # Process category
    "nanofiltration", "nf", "reverse", "osmosis", "ro", "reverse-osmosis",
    "ultrafiltration", "uf", "microfiltration", "mf",
    # Modifications
    "modified", "surface", "surface-modified", "functionalized",
    "coated", "grafted", "decorated", "incorporated", "doped",
    # Filler nouns / connectors
    "with", "containing", "based", "and", "or", "of", "for", "type",
    # Performance adjectives
    "high", "low", "high-rejection", "low-pressure", "high-permeance",
    "high-performance", "selective", "permeable", "tight", "loose",
})

def _is_class_description(name: str) -> bool:
    """True if `name` is a generic class descriptor (e.g. 'non-commercial
    surface-modified membranes') rather than a specific product. Tokenises on
    word boundaries and returns True iff EVERY token is in the generic-token
    set above.

    Names like 'ZIF-8 modified polyamide TFN' return False (the 'zif-8' token
    is non-generic, so a fabricated specific product still gets flagged).
    """
    if not name:
        return False
    # Keep hyphenated compounds together (e.g. 'non-commercial', 'thin-film')
    tokens = re.findall(r"[a-z][a-z0-9\-]*", name.lower())
    if not tokens:
        return False
    return all(t in _CLASS_DESC_TOKENS for t in tokens)

def load_doi_categories(csv_path: str) -> dict[str, str]:
    """Load the {doi (lowercase) -> category} mapping produced by manual
    categorization of fake DOIs (see results/fake_dois_to_categorize.csv).

    Categories: 'non_existent', 'not_relevant', 'relevant_not_in_db'. Any DOI
    not in the file is assumed to be in the DB (i.e. not fake)."""
    import csv
    out: dict[str, str] = {}
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                doi = (row.get("doi") or "").strip().lower()
                cat = (row.get("category") or "").strip()
                if doi and cat:
                    out[doi] = cat
    except FileNotFoundError:
        pass
    return out

def _classify_cite_severity(citations: list[str],
                            known_dois: set[str],
                            doi_categories: Optional[dict[str, str]]) -> str:
    """Compute the per-response citation severity by aggregating per-DOI
    categories. Worst-case wins: if any cited DOI is `non_existent`, the
    response is `fabricated`, even if other cites are real.

    Severity ladder (worst first):
        fabricated         - at least one cited DOI does NOT exist
        irrelevant         - all fakes exist but at least one is on a wrong topic
        extra_only         - all fakes exist and ARE PFAS-membrane papers,
                             just not in our DB (the most defensible failure mode)
        clean              - all cited DOIs are in the DB
    """
    fake_dois = [d.lower() for d in citations if d.lower() not in known_dois]
    if not fake_dois:
        return "clean"
    if doi_categories is None:
        # No categorization available - fall back to a generic 'fake' label
        return "fabricated"
    cats = [doi_categories.get(d, "non_existent") for d in fake_dois]
    # Unknown DOIs default to non_existent (most severe) so we don't let
    # un-categorized fakes inflate the "extra_only" bucket
    if "non_existent" in cats:
        return "fabricated"
    if "not_relevant" in cats:
        return "irrelevant"
    if "relevant_not_in_db" in cats:
        return "extra_only"
    return "fabricated"  # safety: shouldn't reach here

def hallucination_breakdown(answer: Answer,
                            known_pfas: set[str],
                            known_membranes: set[str],
                            known_dois: set[str],
                            doi_categories: Optional[dict[str, str]] = None) -> dict:
    """Decompose hallucination into citation-fabrication vs membrane-fabrication.

    If `doi_categories` is provided, also classify the citation severity
    (see `_classify_cite_severity` for the ladder).

    Returns:
        {
            "cite_hallucinated":     True if any cited DOI is not in `known_dois`,
            "membrane_hallucinated": True if `recommended_membrane` parses to one
                                     or more candidate names AND any candidate
                                     is not in `known_membranes`. Tolerates
                                     comma/'and'/'+'/';' separated lists and
                                     parenthetical type annotations like
                                     '(Commercial)'. Strict semantics: even one
                                     fake name in a list of real ones flags it.
            "membrane_grading_eligible": True if the response actually emitted a
                                        `recommended_membrane` field that
                                        parses to >=1 candidate (a refusal or
                                        a complex-query response with no pick
                                        is not eligible).
            "cite_severity":         one of {'clean', 'extra_only', 'irrelevant',
                                     'fabricated'} when `doi_categories` is
                                     provided, else 'clean' or 'fabricated' only.
            "hallucinated":          cite_hallucinated OR membrane_hallucinated
                                     (kept for backward compatibility with the
                                     headline "any hallucination" metric).
        }
    """
    cite_h = any(d.lower() not in known_dois for d in answer.citations)
    cite_sev = _classify_cite_severity(answer.citations, known_dois, doi_categories)

    membrane_h = False
    membrane_eligible = False
    if answer.recommended_membrane:
        candidates = _split_membrane_field(answer.recommended_membrane)
        # Drop class-description candidates (research-direction answers like
        # "non-commercial surface-modified membranes") - they are not product
        # claims, so grading them against the 81-row membrane table would be a
        # false positive. A specific fabricated name (e.g. "ZIF-8 TFN
        # nanocomposite") still gets through because at least one token is
        # non-generic.
        specific = [c for c in candidates if not _is_class_description(c)]
        if specific:
            membrane_eligible = True
            membrane_h = any(not _is_known_membrane(c, known_membranes)
                             for c in specific)
        # else: only class descriptions → membrane_grading_eligible stays False

    return {
        "cite_hallucinated": cite_h,
        "membrane_hallucinated": membrane_h,
        "membrane_grading_eligible": membrane_eligible,
        "cite_severity": cite_sev,
        "hallucinated": cite_h or membrane_h,
    }

def hallucination_flag(answer: Answer,
                       known_pfas: set[str],
                       known_membranes: set[str],
                       known_dois: set[str]) -> bool:
    """Backward-compat shim: returns the combined OR flag."""
    return hallucination_breakdown(answer, known_pfas, known_membranes,
                                   known_dois)["hallucinated"]

# Top-level grading entry point
@dataclass
class GradedResult:
    prompt_id: str
    rung: str
    answer: Answer
    jaccard: Optional[float] = None
    citation_metrics: Optional[dict] = None
    hallucinated: bool = False               # combined OR (back-compat)
    cite_hallucinated: bool = False          # any cited DOI not in DB
    membrane_hallucinated: bool = False      # recommended_membrane not in DB
    membrane_grading_eligible: bool = False  # response actually emitted a pick
    cite_severity: str = "clean"             # 'clean'|'extra_only'|'irrelevant'|'fabricated'
    refusal_correct: Optional[bool] = None
    notes: list[str] = field(default_factory=list)

def grade(
    prompt_id: str,
    rung: str,
    response_text: str,
    *,
    db_path: str,
    expected_pfas: Optional[str] = None,
    expected_membrane: Optional[str] = None,
    expected_refusal: bool = False,
    known_pfas: Optional[set[str]] = None,
    known_membranes: Optional[set[str]] = None,
    known_dois: Optional[set[str]] = None,
    doi_categories: Optional[dict[str, str]] = None,
) -> GradedResult:
    """Grade a single response against the ground truth.

    Pass `expected_refusal=True` for adversarial / OOD prompts.
    For lookup queries, supply `expected_pfas` and `expected_membrane`.
    """
    answer = parse_response(response_text)
    res = GradedResult(prompt_id=prompt_id, rung=rung, answer=answer)

    # Lazy-load known sets
    known_pfas = known_pfas if known_pfas is not None else get_known_pfas(db_path)
    known_membranes = (known_membranes if known_membranes is not None
                       else get_known_membranes(db_path))
    known_dois = known_dois if known_dois is not None else get_known_dois(db_path)

    # Refusal check
    res.refusal_correct = (answer.refused == expected_refusal)

    # Hallucination flags (separated by failure type for finer-grained reporting)
    h = hallucination_breakdown(answer, known_pfas, known_membranes,
                                known_dois, doi_categories)
    res.cite_hallucinated         = h["cite_hallucinated"]
    res.membrane_hallucinated     = h["membrane_hallucinated"]
    res.membrane_grading_eligible = h["membrane_grading_eligible"]
    res.cite_severity             = h["cite_severity"]
    res.hallucinated              = h["hallucinated"]

    # Range metric (only if we have ground truth)
    if expected_pfas and expected_membrane and not expected_refusal:
        truth = get_ground_truth_range(db_path, expected_pfas, expected_membrane)
        res.jaccard = jaccard_range(answer.rejection_range, truth)
        if truth is None:
            res.notes.append("no_ground_truth_range_available")

        # Citation metric
        relevant = get_dois_for_pair(db_path, expected_pfas, expected_membrane)
        res.citation_metrics = citation_accuracy(answer.citations, relevant, known_dois)

    return res
