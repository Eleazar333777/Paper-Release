"""Convert dataset.xlsx -> SQLite, then pre-compute permeability-selectivity
upper-bound parameters per PFAS via bootstrap.

Usage:
    from code.build_db import build
    build("dataset.xlsx", "pfas_membrane.db")
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize

# Column-name harmonization (the source xlsx has a few unicode artifacts)
_COLUMN_RENAME = {
    "Membrane": "membrane",
    "Type": "membrane_type",
    "A": "A",
    "B": "B",
    "A/B": "A_over_B",
    "f": "f",
    "MWCO (Da)": "mwco_da",
    "Isoelectric point": "iep",
    "Water contact angle(°）": "contact_angle_deg",
    "PFAS": "pfas",
    "Mw": "pfas_mw",
    "SMILES": "smiles",
    "Van der Waals radius(Å)": "vdw_radius_a",
    "Minimum projection radius (Å)": "min_proj_radius_a",
    "Maximum projection radius (Å)": "max_proj_radius_a",
    "Compound size (Å)": "compound_size_a",
    "log Kow": "log_kow",
    "log Dow(6.5)": "log_dow_65",
    "pKa": "pka",
    "Initial concentration (ng/L)": "init_conc_ngl",
    "IS (mM)": "ionic_strength_mm",
    "Pressure (psi)": "pressure_psi",
    "pH": "pH",
    "Removal_rate": "rejection_pct",
    "ref": "ref",
    "DOI": "doi",
}

# Keep these columns (in this order) in the SQLite table
_KEEP_COLUMNS = list(_COLUMN_RENAME.values())

def _load_master_sheet(xlsx_path: str | Path) -> pd.DataFrame:
    """Load Sheet1 (the comprehensive master) and harmonize column names."""
    df = pd.read_excel(xlsx_path, sheet_name="Sheet1")

    # Rename - also tolerate slight variations in column header text
    rename_map = {}
    for col in df.columns:
        norm = re.sub(r"\s+", " ", str(col)).strip()
        for src, dst in _COLUMN_RENAME.items():
            if norm == src or norm.startswith(src.split(" ")[0]) and src in (
                "water permeability（L m-2 h-1 bar-1）",
            ):
                rename_map[col] = dst
                break
        # Fallback: try fuzzy match by stripping all non-alphanumerics
        else:
            for src, dst in _COLUMN_RENAME.items():
                if re.sub(r"\W+", "", norm).lower() == re.sub(r"\W+", "", src).lower():
                    rename_map[col] = dst
                    break
    df = df.rename(columns=rename_map)

    # Keep only known columns; add any missing as NaN
    for c in _KEEP_COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[_KEEP_COLUMNS].copy()

    # Coerce numerics
    numeric_cols = [
        "A", "B", "A_over_B", "f", "mwco_da", "iep", "contact_angle_deg",
        "pfas_mw", "vdw_radius_a", "min_proj_radius_a", "max_proj_radius_a",
        "compound_size_a", "log_kow", "log_dow_65", "pka",
        "init_conc_ngl", "ionic_strength_mm", "pressure_psi", "pH",
        "rejection_pct",
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    # Add row id for citation lookup
    df.insert(0, "id", np.arange(1, len(df) + 1))
    return df

# Upper-bound fitting:   A/B = c * A^(-n)   <=>   log(A/B) = log(c) - n*log(A)
#
# Algorithm (matches the original CetaraGPT manuscript Figure 4 methodology
# as best as can be inferred - the manuscript does not state the leading-edge
# selection rule explicitly, but their reported steep slopes (n = 2.13 to 5.00)
# imply a tight selection):
#
#   1. Bin commercial-only points by log(A) into N_BINS percentile-equal bins.
#   2. Keep ONLY the single point with the highest A/B per bin (top-1 per bin).
#   3. Fit log10(A/B) = log10(c) - n * log10(A) by ordinary least squares.
#   4. Bootstrap 500x for 95% CI on (c, n).
#
# Two-line treatment (also from the original):
#   - Fit commercial-only first → (c_com, n_com)  [solid line in Fig 4].
#   - If non-commercial points exceed the commercial bound by `break_margin`,
#     ALSO fit a "non-commercial-included" line WITH n HELD FIXED at n_com
#     (only c is re-fit so the line envelopes all points). This produces the
#     dashed lines in original Figure 4.
N_BINS_DEFAULT = 8
MIN_FIT_POINTS = 3   # require at least this many leading-edge points to fit

def _leading_edge_mask(A: np.ndarray, AB: np.ndarray,
                       n_bins: int = N_BINS_DEFAULT) -> np.ndarray:
    """Select leading-edge (upper envelope) points in (log A, log A/B) space.

    Algorithm: walk left-to-right through points sorted by A; keep a point if
    its A/B is greater than every previously-kept point's A/B AT-OR-BELOW the
    currently-implied envelope. Equivalent to the upper monotonic envelope
    used in classic permeability-selectivity upper-bound analyses (Robeson 1991,
    Park et al. 2017, Yang et al. 2019). This isolates only the points that
    actually sit on the leading edge.
    """
    n = len(A)
    if n < MIN_FIT_POINTS:
        return np.ones_like(A, dtype=bool)
    # Sort by A ascending
    order = np.argsort(A)
    keep_idx = []
    # Walk right-to-left and keep points where A/B exceeds all rightward-kept
    # points (= upper envelope as A increases right-to-left).
    # Equivalently: walking left-to-right, keep points where A/B is >= max
    # of all subsequent points; this is the "upper-left frontier".
    # Implementation: from right to left, keep points whose A/B is greater
    # than the running max of all already-kept A/B.
    running_max = -np.inf
    for i in reversed(order):
        if AB[i] > running_max:
            keep_idx.append(i)
            running_max = AB[i]
    keep = np.zeros(n, dtype=bool)
    keep[keep_idx] = True
    return keep

def _fit_power_law(A: np.ndarray, AB: np.ndarray) -> tuple[float, float] | tuple[None, None]:
    """OLS fit of log(A/B) = log(c) - n * log(A). Returns (c, n) or (None, None)."""
    mask = (A > 0) & (AB > 0) & np.isfinite(A) & np.isfinite(AB)
    if mask.sum() < 3:
        return None, None
    log_A = np.log10(A[mask])
    log_AB = np.log10(AB[mask])
    try:
        slope, intercept = np.polyfit(log_A, log_AB, 1)
        return float(10 ** intercept), float(-slope)
    except Exception:
        return None, None

def _refit_c_with_fixed_n(A: np.ndarray, AB: np.ndarray, n: float) -> float | None:
    """With slope -n held fixed, find c such that the line envelopes ALL points
    from above (parallel-shift up). c = max over points of (A/B) * A^n."""
    mask = (A > 0) & (AB > 0) & np.isfinite(A) & np.isfinite(AB)
    if not mask.any():
        return None
    A_, AB_ = A[mask], AB[mask]
    return float((AB_ * A_ ** n).max())

def _bootstrap_fit(A: np.ndarray, AB: np.ndarray,
                   n_iter: int = 500, seed: int = 0) -> dict:
    """Bootstrap CI for (c, n) from a leading-edge OLS fit."""
    le = _leading_edge_mask(A, AB)
    A_le, AB_le = A[le], AB[le]
    c0, n0 = _fit_power_law(A_le, AB_le)
    if c0 is None or len(A_le) < MIN_FIT_POINTS:
        return {"c": None, "n": None, "c_lower": None, "c_upper": None,
                "n_lower": None, "n_upper": None, "n_points": int(le.sum())}
    rng = np.random.default_rng(seed)
    cs, ns = [], []
    for _ in range(n_iter):
        idx = rng.integers(0, len(A_le), size=len(A_le))
        c, n = _fit_power_law(A_le[idx], AB_le[idx])
        if c is not None and n is not None:
            cs.append(c); ns.append(n)
    if not cs:
        return {"c": c0, "n": n0, "c_lower": None, "c_upper": None,
                "n_lower": None, "n_upper": None, "n_points": int(le.sum())}
    return {
        "c": c0, "n": n0,
        "c_lower": float(np.percentile(cs, 2.5)),
        "c_upper": float(np.percentile(cs, 97.5)),
        "n_lower": float(np.percentile(ns, 2.5)),
        "n_upper": float(np.percentile(ns, 97.5)),
        "n_points": int(le.sum()),
    }

def _compute_upper_bounds(records: pd.DataFrame, min_n: int = 6,
                           break_margin: float = 1.10) -> pd.DataFrame:
    """For each PFAS, fit:
        - commercial-only upper bound (solid line)
        - if non-commercial points exceed it by `break_margin`, ALSO produce a
          non-commercial-extended line with n held fixed (dashed line)

    Returns columns: pfas, c, n, c_lower, c_upper, n_lower, n_upper, n_points,
                     c_all, n_all, n_breakers, breaks
    """
    rows = []
    for pfas, sub in records.groupby("pfas"):
        sub = sub.dropna(subset=["A", "A_over_B"])
        sub = sub[(sub["A"] > 0) & (sub["A_over_B"] > 0)]
        com = sub[sub["membrane_type"].astype(str).str.upper() == "COMMERCIAL"]
        if len(com) < min_n:
            continue
        bs = _bootstrap_fit(com["A"].to_numpy(), com["A_over_B"].to_numpy())
        if bs["c"] is None:
            continue
        bs["pfas"] = pfas
        bs["c_all"] = None
        bs["n_all"] = None
        bs["n_breakers"] = 0
        bs["breaks"] = False

        # Two-line treatment: do non-commercial points break the commercial bound?
        noncom = sub[sub["membrane_type"].astype(str).str.upper() == "NON-COMMERCIAL"]
        if len(noncom) >= 1:
            A_nc = noncom["A"].to_numpy()
            AB_nc = noncom["A_over_B"].to_numpy()
            bound_at_nc = bs["c"] * A_nc ** (-bs["n"])
            breakers_mask = AB_nc > bound_at_nc * break_margin
            if breakers_mask.any():
                A_all = np.concatenate([com["A"].to_numpy(), A_nc])
                AB_all = np.concatenate([com["A_over_B"].to_numpy(), AB_nc])
                c_all = _refit_c_with_fixed_n(A_all, AB_all, n=bs["n"])
                if c_all is not None and c_all > bs["c"]:
                    bs["c_all"] = c_all
                    bs["n_all"] = bs["n"]
                    bs["n_breakers"] = int(breakers_mask.sum())
                    bs["breaks"] = True
        rows.append(bs)

    cols = ["pfas", "c", "n", "c_lower", "c_upper", "n_lower", "n_upper",
            "n_points", "c_all", "n_all", "n_breakers", "breaks"]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)[cols]

# Public entry point
def build(xlsx_path: str | Path, db_path: str | Path) -> dict:
    """Build the SQLite database from the Excel file.

    Idempotent: re-running drops + recreates the tables in-place (via SQL)
    rather than deleting the file. This is robust to Windows file locks
    held by other Python processes (e.g., a Jupyter kernel that already has
    an open sqlite3 connection to the same DB).

    Returns:
        Summary dict with row counts.
    """
    xlsx_path = Path(xlsx_path)
    db_path = Path(db_path)

    records = _load_master_sheet(xlsx_path)
    upper_bounds = _compute_upper_bounds(records)

    conn = sqlite3.connect(db_path)
    try:
        # Drop existing tables/indexes (safe even if they don't exist) - this
        # lets us rebuild without deleting the .db file, which Windows would
        # refuse if another process holds an open handle to it.
        conn.execute("DROP INDEX IF EXISTS idx_records_pfas")
        conn.execute("DROP INDEX IF EXISTS idx_records_membrane")
        conn.execute("DROP INDEX IF EXISTS idx_records_rejection")
        conn.execute("DROP TABLE IF EXISTS records")
        conn.execute("DROP TABLE IF EXISTS upper_bounds")
        conn.commit()

        records.to_sql("records", conn, index=False)
        upper_bounds.to_sql("upper_bounds", conn, index=False)
        conn.execute("CREATE INDEX idx_records_pfas       ON records(pfas)")
        conn.execute("CREATE INDEX idx_records_membrane   ON records(membrane)")
        conn.execute("CREATE INDEX idx_records_rejection  ON records(rejection_pct)")
        conn.commit()
    finally:
        conn.close()

    return {
        "n_records": len(records),
        "n_pfas": records["pfas"].nunique(),
        "n_membranes": records["membrane"].nunique(),
        "n_upper_bounds": len(upper_bounds),
        "db_path": str(db_path),
    }

def get_schema_text(db_path: str | Path) -> str:
    """Return a compact schema description for use in text-to-SQL prompts."""
    return """
TABLE records (1,017 rows; one row = one PFAS-membrane experimental observation):
  id                 INTEGER PRIMARY KEY
  membrane           TEXT     -- membrane name (81 unique, e.g. 'NF270', 'NF90', 'HA-TFC')
  membrane_type      TEXT     -- 'Commercial' or 'Non-commercial'
  A                  REAL     -- water permeance, LMH/bar
  B                  REAL     -- solute (PFAS) permeability, LMH
  A_over_B           REAL     -- water/PFAS selectivity, dimensionless
  f                  REAL     -- 1 - 1/selectivity (numerical convenience)
  mwco_da            REAL     -- molecular weight cutoff, Da
  iep                REAL     -- isoelectric point of membrane
  contact_angle_deg  REAL     -- water contact angle, degrees
  pfas               TEXT     -- PFAS species (21 unique, e.g. 'PFOA', 'PFOS', 'PFBA')
  pfas_mw            REAL     -- PFAS molecular weight, g/mol
  smiles             TEXT     -- PFAS SMILES string
  vdw_radius_a       REAL     -- van der Waals radius, angstrom
  compound_size_a    REAL     -- characteristic compound size, angstrom
  log_kow            REAL     -- log octanol-water partition coefficient
  log_dow_65         REAL     -- log distribution coefficient at pH 6.5
  pka                REAL     -- PFAS pKa
  init_conc_ngl      REAL     -- initial PFAS concentration, ng/L
  ionic_strength_mm  REAL     -- ionic strength, mM
  pressure_psi       REAL     -- transmembrane pressure, psi
  pH                 REAL     -- feed pH
  rejection_pct      REAL     -- PFAS rejection percentage [0-100]
  ref                TEXT     -- paper title
  doi                TEXT     -- paper DOI URL

TABLE upper_bounds (per-PFAS power-law fit: A/B = c * A^(-n)):
  pfas         TEXT     -- PFAS species
  c            REAL     -- pre-exponential factor (commercial-only fit)
  n            REAL     -- exponent / slope on log-log (commercial-only fit)
  c_lower      REAL     -- 95% CI lower bound on c (bootstrap)
  c_upper      REAL     -- 95% CI upper bound on c
  n_lower      REAL     -- 95% CI lower bound on n
  n_upper      REAL     -- 95% CI upper bound on n
  n_points     INTEGER  -- number of leading-edge points used in the fit
  c_all        REAL     -- pre-exponential factor for the all-membrane (com+noncom) line
                       --   (NULL if non-commercial does not break the commercial bound)
  n_all        REAL     -- slope for the all-membrane line (held = n by construction)
  n_breakers   INTEGER  -- number of non-commercial points that broke the commercial bound
  breaks       INTEGER  -- 1 if non-commercial breaks the commercial bound, else 0

Notes:
- All numeric ranges should be respected; e.g. rejection_pct is [0, 100], not [0, 1].
- Some columns may have NULLs (e.g. mwco_da is ~8% null; zeta_potential not retained).
- The same (pfas, membrane) pair can appear multiple times under different conditions.
""".strip()

if __name__ == "__main__":
    import sys
    xlsx = sys.argv[1] if len(sys.argv) > 1 else "dataset.xlsx"
    db = sys.argv[2] if len(sys.argv) > 2 else "pfas_membrane.db"
    summary = build(xlsx, db)
    print(summary)
