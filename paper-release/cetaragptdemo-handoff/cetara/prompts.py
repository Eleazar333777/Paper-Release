"""Benchmark prompts - Medium scope (~30 prompts).

Three categories:
  1. lookup            : 18 PFAS-membrane pairs (matches the original Fig 6)
  2. multi_objective   :  3 dual-PFAS scenarios (matches the original Fig 5)
  3. ood_adversarial   : ~10 prompts that should trigger refusal or careful handling

Each prompt is a dict:
    {
        "id":          "...",                  # short stable identifier
        "category":    "lookup" | "multi_objective" | "ood_adversarial",
        "user_query":  "...",                  # what gets sent to each rung
        "expected_pfas": "PFOA",               # for grading lookup queries
        "expected_membrane": "NF270",
        "expected_refusal": False,
        "complexity_bin": "simple" | "ranking" | "multi_objective" | "ood",
        "notes":       "...",                  # what we expect / why
    }
"""
from __future__ import annotations

# 1. Lookup queries (18 = 6 PFAS x 3 membranes) - matches original Fig 6
_LOOKUP_PFAS = ["PFOS", "PFOA", "PFHxA", "PFBS", "PFHpA", "PFBA"]
_LOOKUP_MEMBRANES = ["NF270", "NF90", "DL"]

LOOKUP_PROMPTS = []
for pfas in _LOOKUP_PFAS:
    for membrane in _LOOKUP_MEMBRANES:
        LOOKUP_PROMPTS.append({
            "id": f"lookup_{pfas}_{membrane}",
            "category": "lookup",
            "user_query": (
                f"What is the range of {pfas} rejection (in %) reported in the literature "
                f"for the {membrane} polyamide membrane? Provide the lowest and highest "
                f"rejection values, and cite the source DOIs."
            ),
            "expected_pfas": pfas,
            "expected_membrane": membrane,
            "expected_refusal": False,
            "complexity_bin": "simple",
            "notes": "single-pair lookup; ground-truth range from DB",
        })

# 2. Multi-objective queries - joint constraints + optimization
# First 3 reproduce the original manuscript's Fig 5 scenarios verbatim.
# Remaining 7 (added for journal-quality statistical power) cover:
#   - new PFAS pairs spanning long-chain, short-chain, and PFCA-PFSA mixes
#   - 3-PFAS coverage (more constraints to handle)
#   - alternative optimization objective (selectivity instead of permeance)
#   - permeance as a CONSTRAINT (not just an objective)
#   - tiered/asymmetric thresholds
MULTI_OBJ_PROMPTS = [
    # ----- Original Fig 5 scenarios (3) -----
    {
        "id": "multi_PFOA_PFHxA",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOA rejection > 90% "
            "AND PFHxA rejection > 92% simultaneously, while maximizing water permeance. "
            "Name the membrane, give its water permeance and both rejection values, and "
            "cite the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Original Fig 5A. Expected pick: HA-TFC (or similar Pareto-optimal).",
    },
    {
        "id": "multi_PFOS_GenX",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOS rejection > 95% "
            "AND GenX rejection > 97% simultaneously, while maximizing water permeance. "
            "Name the membrane, give its water permeance and both rejection values, and "
            "cite the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Original Fig 5B.",
    },
    {
        "id": "multi_PFBS_PFHxS",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFBS rejection > 85% "
            "AND PFHxS rejection > 90% simultaneously, while maximizing water permeance. "
            "Name the membrane, give its water permeance and both rejection values, and "
            "cite the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Original Fig 5C.",
    },
    # ----- Added for review (7) -----
    {
        "id": "multi_PFOA_PFOS",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves both PFOA rejection > 95% "
            "AND PFOS rejection > 95% (the two most regulated long-chain PFAS), while "
            "maximizing water permeance. Name the membrane, report water permeance and "
            "both rejection values, and cite the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Two most regulated long-chain PFAS. Realistic drinking-water scenario.",
    },
    {
        "id": "multi_PFBA_PFBS",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFBA rejection > 80% "
            "AND PFBS rejection > 80% simultaneously, while maximizing water permeance. "
            "Name the membrane, give water permeance and both rejection values, and cite "
            "the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Short-chain PFAS pair (PFBA + PFBS), genuinely difficult - short-chain "
                  "rejection is intrinsically lower and few membranes meet both."),
    },
    {
        "id": "multi_PFNA_PFHxA",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFNA rejection > 90% "
            "AND PFHxA rejection > 90% simultaneously, while maximizing water permeance. "
            "Name the membrane, give water permeance and both rejection values, and cite "
            "the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Same-family PFCAs of different chain lengths.",
    },
    {
        "id": "multi_three_pfas_PFSA_series",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOS rejection > 95%, "
            "PFHxS rejection > 90%, AND PFBS rejection > 80% simultaneously (full PFSA "
            "homologous series with descending thresholds for shorter chains), while "
            "maximizing water permeance. Name the membrane, give water permeance and all "
            "three rejection values, and cite source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Three-PFAS constraint with tiered thresholds (PFSA homologs).",
    },
    {
        "id": "multi_three_pfas_PFCA_series",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOA rejection > 95%, "
            "PFHxA rejection > 90%, AND PFBA rejection > 80% simultaneously (full PFCA "
            "homologous series with descending thresholds for shorter chains), while "
            "maximizing water permeance. Name the membrane, give water permeance and all "
            "three rejection values, and cite source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Three-PFAS constraint with tiered thresholds (PFCA homologs).",
    },
    {
        "id": "multi_max_selectivity_PFOS_GenX",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOS rejection > 90% "
            "AND GenX rejection > 90%, but rather than maximizing water permeance, "
            "maximize the water/PFAS selectivity (A/B). Name the membrane, give the "
            "selectivity and both rejection values, and cite source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Different optimization objective: max A/B instead of max A.",
    },
    {
        "id": "multi_high_recovery_PFOA",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single commercial polyamide membrane that simultaneously achieves "
            "PFOA rejection > 95% AND water permeance > 5 LMH/bar (treating both as "
            "constraints, not as optimization targets). If multiple satisfy both, return "
            "the one with the highest combined score (rejection × permeance). Cite the "
            "source paper."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Permeance as a CONSTRAINT (not just objective) - tests whether the "
                  "model handles a numeric threshold on a continuous variable."),
    },
    # ----- Added second batch (8 more, bringing total to 18) -----
    {
        "id": "multi_PFOA_PFBA",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOA rejection > 90% "
            "AND PFBA rejection > 80% simultaneously, while maximizing water permeance. "
            "Name the membrane, give water permeance and both rejection values, and cite "
            "the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Wide chain-length spread within PFCAs (C8 + C4). Tests membranes "
                  "that bridge long- and short-chain rejection."),
    },
    {
        "id": "multi_PFOS_PFBS",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOS rejection > 95% "
            "AND PFBS rejection > 85% simultaneously, while maximizing water permeance. "
            "Name the membrane, give water permeance and both rejection values, and cite "
            "the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": "Wide chain-length spread within PFSAs (C8 + C4).",
    },
    {
        "id": "multi_GenX_PFOA",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves GenX rejection > 90% "
            "AND PFOA rejection > 95% simultaneously, while maximizing water permeance. "
            "Name the membrane, give water permeance and both rejection values, and cite "
            "the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Cross-chemistry: ether-linked replacement (GenX) + regulated legacy "
                  "long-chain (PFOA). Realistic post-PFOA-phaseout scenario."),
    },
    {
        "id": "multi_PFHxS_PFHxA",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFHxS rejection > 90% "
            "AND PFHxA rejection > 90% simultaneously, while maximizing water permeance. "
            "Name the membrane, give water permeance and both rejection values, and cite "
            "the source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Same chain length (C6) but different headgroup (sulfonate vs "
                  "carboxylate). Tests whether membrane discriminates by headgroup."),
    },
    {
        "id": "multi_drinking_water_pH",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOA rejection > 90% "
            "AND PFOS rejection > 90% simultaneously, USING ONLY studies conducted at "
            "drinking-water-relevant pH (pH 6.0–8.0). Maximize water permeance. Name "
            "the membrane, give water permeance, both rejection values, the pH "
            "condition, and cite source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Adds an OPERATIONAL constraint (pH range) on top of dual rejection "
                  "thresholds. Tests filtering on a continuous experimental parameter."),
    },
    {
        "id": "multi_low_pressure_PFOA",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOA rejection > 90% "
            "USING ONLY studies conducted at LOW operating pressure (<= 100 psi, for "
            "energy-efficient operation), while maximizing water permeance. Name the "
            "membrane, report water permeance, rejection, the operating pressure, and "
            "cite source paper(s)."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Operational constraint on pressure (≤ 100 psi). Realistic energy-"
                  "efficiency framing - only some studies report at low pressure."),
    },
    {
        "id": "multi_commercial_only_PFOA_PFOS",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single COMMERCIAL polyamide membrane (not a research-grade "
            "modification) that achieves PFOA rejection > 95% AND PFOS rejection > 95% "
            "simultaneously, while maximizing water permeance. Name the membrane, give "
            "water permeance and both rejection values, and cite source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Type-restricted (commercial only). Tests filtering on the "
                  "membrane_type column AND the dual rejection constraint together."),
    },
    {
        "id": "multi_balance_PFOA_PFHxA",
        "category": "multi_objective",
        "user_query": (
            "Recommend a single polyamide membrane that achieves PFOA rejection > 90% "
            "AND PFHxA rejection > 90%. Among membranes meeting both, rather than "
            "maximizing permeance alone, maximize the BALANCED score A × (A/B) "
            "(permeance times selectivity, the same metric used to rank Pareto-optimal "
            "membranes). Name the membrane, give A, A/B, both rejections, and cite "
            "source paper(s)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "multi_objective",
        "notes": ("Composite optimization objective: maximize A · (A/B) under dual "
                  "rejection constraints. Tests whether the model can use the same "
                  "ranking metric as the recommendation prompts but with constraints."),
    },
]

# 3. OOD / adversarial (~10) - these should trigger refusal or careful handling
OOD_PROMPTS = [
    {
        "id": "ood_fake_pfas",
        "category": "ood_adversarial",
        "user_query": (
            "What is the rejection range of PFXYZ-9 by the NF270 membrane?"
        ),
        "expected_pfas": "PFXYZ-9",
        "expected_membrane": "NF270",
        "expected_refusal": True,
        "complexity_bin": "ood",
        "notes": "Fake PFAS; should refuse / say not in dataset.",
    },
    {
        "id": "ood_fake_membrane",
        "category": "ood_adversarial",
        "user_query": (
            "What is the rejection range of PFOA by the MagicRO-7000 membrane?"
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": "MagicRO-7000",
        "expected_refusal": True,
        "complexity_bin": "ood",
        "notes": "Fake membrane; should refuse.",
    },
    {
        "id": "ood_out_of_scope_contaminant",
        "category": "ood_adversarial",
        "user_query": (
            "Recommend a membrane for arsenic removal."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": True,
        "complexity_bin": "ood",
        "notes": "Out-of-scope contaminant (not PFAS).",
    },
    {
        "id": "ood_impossible_constraints",
        "category": "ood_adversarial",
        "user_query": (
            "Recommend a polyamide membrane that achieves >99.5% rejection of PFBA "
            "with water permeance > 100 LMH/bar."
        ),
        "expected_pfas": "PFBA",
        "expected_membrane": None,
        "expected_refusal": True,
        "complexity_bin": "ood",
        "notes": ("Impossible - short-chain PFBA at 99.5% is far above the upper bound "
                  "for any membrane, and 100 LMH/bar is unphysically high for NF/RO."),
    },
    {
        "id": "ood_unsupported_technology",
        "category": "ood_adversarial",
        "user_query": (
            "Recommend a granular activated carbon system for PFOS removal."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": True,
        "complexity_bin": "ood",
        "notes": "Out-of-scope technology (GAC, not membrane).",
    },
    {
        "id": "ood_extreme_pH",
        "category": "ood_adversarial",
        "user_query": (
            "What is the rejection of PFOA by NF270 at pH 1?"
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": "NF270",
        "expected_refusal": True,
        "complexity_bin": "ood",
        "notes": ("pH 1 is far outside the dataset's operating range; should refuse "
                  "or explicitly flag the extrapolation."),
    },
    {
        "id": "ood_citation_verify_real",
        "category": "ood_adversarial",
        "user_query": (
            "Which published paper reports PFOA rejection above 99% by the NF90 membrane? "
            "Provide the DOI."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": "NF90",
        "expected_refusal": False,
        "complexity_bin": "ood",
        "notes": ("Citation-verification: agent should look up real records and "
                  "cite a real DOI. Vanilla LLM tends to hallucinate."),
    },
    {
        "id": "ood_ambiguous_membrane_name",
        "category": "ood_adversarial",
        "user_query": (
            "What is the rejection of PFOA by the NF-270 membrane?"
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": "NF270",
        "expected_refusal": False,
        "complexity_bin": "ood",
        "notes": ("Same membrane with hyphen in the name. Agent should normalize and "
                  "answer correctly; baselines may treat as new entity."),
    },
    {
        "id": "ood_short_chain_innovation",
        "category": "ood_adversarial",
        "user_query": (
            "What is the highest rejection of PFBA achieved by any non-commercial "
            "membrane, and which paper reports it?"
        ),
        "expected_pfas": "PFBA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "ranking",
        "notes": ("Ranking + filter + citation. Agent should chain "
                  "filter_records -> rank_membranes -> cite_papers."),
    },
    {
        "id": "ood_aggregate_count",
        "category": "ood_adversarial",
        "user_query": (
            "How many distinct non-commercial polyamide membranes in the dataset have "
            "been tested on PFOS? List them."
        ),
        "expected_pfas": "PFOS",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "ranking",
        "notes": "Aggregate query; agent should filter then list distinct membranes.",
    },
]

# 4. Single-PFAS membrane recommendation prompts (used for Figure 4 overlays)
# Replicates the original CetaraGPT manuscript Figure 4 prompt design exactly:
# "top 3 commercial AND top 3 non-commercial membranes for a target PFAS,
#  optimizing the product of water permeance A and water-PFAS selectivity A/B."
# 17 PFAS = the same set that gets fitted upper bounds in the original Figure 4.
_RECOMMEND_PFAS = [
    # PFSAs (sulfonates)  - original Fig 4A, ordered by C-chain length
    "PFBS", "PFPeS", "PFHxS", "PFHpS", "PFOS",
    # Other PFAS         - original Fig 4B
    "PFMOPrA", "PFMOBA", "4:2FTS", "GenX", "6:2FTS",
    # PFCAs (carboxylates) - original Fig 4C, ordered by C-chain length
    "PFBA", "PFPeA", "PFHxA", "PFHpA", "PFOA", "PFNA", "PFDA",
]

RECOMMEND_PROMPTS = [
    {
        "id": f"recommend_top_{p}",
        "category": "recommendation",
        "user_query": (
            f"For {p} removal by polyamide nanofiltration / reverse osmosis "
            f"membranes, recommend the TOP 3 COMMERCIAL membranes AND the TOP 3 "
            f"NON-COMMERCIAL membranes from the literature, ranked by IDEAL-POINT "
            f"DISTANCE in normalized log10(A)-log10(A/B) space. Smaller distance "
            f"to the ideal point (highest water permeance A AND highest "
            f"water-PFAS selectivity A/B) means a better balance of permeance and "
            f"selectivity. Use the BEST literature record per membrane (the one "
            f"closest to the ideal point), not a mean over duplicate measurements. "
            f"For each of the 6 membranes, provide: (i) membrane name, "
            f"(ii) commercial vs non-commercial classification, (iii) water "
            f"permeance A, (iv) selectivity A/B, (v) rejection rate, and "
            f"(vi) the source paper DOI."
        ),
        "expected_pfas": p,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "ranking",
        "notes": ("Top-3 commercial + top-3 non-commercial recommendation. "
                  "Scoring criterion (golden answer): smallest distance to the "
                  "ideal point (1, 1) after min-max normalizing log10(A) and "
                  "log10(A/B) per PFAS, keeping the best record per "
                  "(membrane, type)."),
    }
    for p in _RECOMMEND_PFAS
]

# 5. Multi-step / agentic-required prompts
# Designed so single-shot text-to-SQL hits a wall and the agentic paradigm's
# multi-step planning loop is genuinely required. Each prompt either:
#   - has CONDITIONAL fallback logic ("if no result, try X")
#   - requires CROSS-TOOL composition (filter + upper_bound + cite)
#   - asks for SELF-VERIFICATION of the recommendation
#   - or requires CONSTRAINT-RELAXATION reasoning
# A well-instructed agent should chain 3+ tool calls and beat single-SQL here.
AGENTIC_PROMPTS = [
    {
        "id": "agentic_conditional_fallback_PFOA",
        "category": "agentic_required",
        "user_query": (
            "Find the best COMMERCIAL polyamide membrane for PFOA removal "
            "(ranked by A·A/B). If no commercial membrane achieves at least 95% "
            "PFOA rejection, ALSO provide the best non-commercial alternative "
            "as a fallback. State clearly which case applies."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Conditional logic: agent must filter commercial first, evaluate "
                  "the result, then decide whether to call filter again with "
                  "non-commercial. SQL has no 'if no rows then' construct."),
    },
    {
        "id": "agentic_constraint_diagnostics",
        "category": "agentic_required",
        "user_query": (
            "Find a single commercial polyamide membrane that achieves PFOA "
            "rejection >99%, PFOS rejection >99%, AND water permeance A > 25 "
            "LMH/bar simultaneously. If no such membrane exists, identify which "
            "of the three constraints is the binding one - by relaxing each "
            "constraint separately and reporting which relaxation enables a "
            "match."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Diagnostic chain: filter with all 3 constraints → if empty, "
                  "filter 3 more times each relaxing one constraint, then "
                  "compare results. Single SQL cannot diagnose binding constraint."),
    },
    {
        "id": "agentic_within_pct_of_bound_PFOA",
        "category": "agentic_required",
        "user_query": (
            "For PFOA, identify which polyamide membranes lie within 30% of the "
            "fitted upper-bound trade-off (A/B = c·A^(-n)). List up to 5 such "
            "membranes, sorted by closeness to the bound, and indicate whether "
            "each is commercial or non-commercial."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Cross-tool: must call get_upper_bound(PFOA) AND filter_records "
                  "AND compute distance to bound for each. Single SQL would "
                  "require the LLM to either embed c, n constants in the query "
                  "or do a complex JOIN with the upper_bounds table."),
    },
    {
        "id": "agentic_multi_pfas_coverage",
        "category": "agentic_required",
        "user_query": (
            "I need to remove a mixture of three PFAS - PFOA, PFOS, and PFBA - "
            "all to at least 90% rejection with a SINGLE polyamide membrane. "
            "Find one if it exists. If no single membrane satisfies all three, "
            "identify the best two-membrane combination (one each, in series) "
            "that covers all three PFAS."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Iterative coverage: agent must filter for each PFAS, intersect, "
                  "then if empty, search for membrane pairs that jointly cover. "
                  "Combinatorial search is awkward in single-shot SQL."),
    },
    {
        "id": "agentic_self_verification_PFOA",
        "category": "agentic_required",
        "user_query": (
            "Recommend the best NON-COMMERCIAL polyamide membrane for PFOA "
            "removal. After identifying it, verify your recommendation by "
            "listing the specific record IDs (and DOIs) that support the claim, "
            "and report the experimental conditions (pressure, pH, initial "
            "concentration) for each supporting record."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Self-verification chain: rank → cite → re-filter for those "
                  "specific record IDs to retrieve detailed conditions. Three+ "
                  "tool calls needed; provenance is the key feature."),
    },
    {
        "id": "agentic_steepest_tradeoff",
        "category": "agentic_required",
        "user_query": (
            "Among the PFAS species in the dataset that have fitted "
            "permeability–selectivity upper bounds, which 3 show the STEEPEST "
            "trade-off (i.e., the largest n exponent)? Report the n value, the "
            "chemical class (PFSA, PFCA, or other), and one example membrane "
            "near each bound."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Cross-PFAS aggregation: agent must call get_upper_bound for "
                  "many PFAS, sort by n, then for top-3 call rank_membranes. "
                  "Can be done in SQL as one query but requires multi-table JOIN "
                  "that LLMs frequently get wrong."),
    },
    # ----- Added for review (12) -----
    {
        "id": "agentic_iterative_relaxation_PFOA",
        "category": "agentic_required",
        "user_query": (
            "Find a commercial polyamide membrane that achieves PFOA rejection > 99%. "
            "If none exists in the dataset, progressively relax the threshold by 1% "
            "at a time (98%, 97%, …) until you find at least one match. Report the "
            "first achievable threshold and the membrane(s) at that level."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Iterative relaxation loop - pure SQL would require either knowing "
                  "the answer in advance or running multiple queries with intermediate "
                  "evaluation. The agent must adapt its query based on prior results."),
    },
    {
        "id": "agentic_compare_NF270_NF90_PFOA",
        "category": "agentic_required",
        "user_query": (
            "Compare NF270 and NF90 head-to-head on PFOA removal. For each membrane "
            "report: (a) rejection range (min and max), (b) mean water permeance A, "
            "(c) number of independent studies, and (d) typical operating conditions "
            "(pH range, pressure range). Then state which membrane is preferable for "
            "PFOA removal and justify briefly."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Two parallel multi-metric retrievals + side-by-side synthesis. "
                  "Requires the agent to plan two independent filter chains then "
                  "compare them, not just emit one large SQL query."),
    },
    {
        "id": "agentic_outlier_detection_PFOS",
        "category": "agentic_required",
        "user_query": (
            "For PFOS rejection across all commercial membranes in the dataset, "
            "identify any outlier records - i.e., individual measurements whose "
            "rejection is more than 2 standard deviations below the membrane's own "
            "mean rejection (suggesting unusual experimental conditions). For each "
            "outlier, report the membrane, the outlier rejection value, the typical "
            "mean rejection for that membrane, and the source DOI."
        ),
        "expected_pfas": "PFOS",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Per-membrane statistical analysis: agent must first compute mean "
                  "and stddev per membrane, then re-filter to find records below "
                  "the per-membrane threshold. Two-pass aggregation."),
    },
    {
        "id": "agentic_optimal_pH_PFOA_NF270",
        "category": "agentic_required",
        "user_query": (
            "Across all studies of PFOA rejection by NF270, identify the pH range "
            "that maximizes mean rejection. Report the optimal pH bin (e.g., pH 5–6, "
            "pH 6–7, pH 7–8, pH 8–9), the mean rejection in that bin, and the "
            "supporting DOIs."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": "NF270",
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Operational-condition optimization. Agent must filter, bin by pH, "
                  "aggregate per bin, then return the top bin. Single SQL would need "
                  "CASE statements that LLMs often get wrong."),
    },
    {
        "id": "agentic_chain_length_trend_NF270",
        "category": "agentic_required",
        "user_query": (
            "Investigate how PFAS chain length affects rejection by the NF270 "
            "membrane. Report mean rejection for at least 4 PFCAs of different chain "
            "lengths (e.g., PFBA, PFHxA, PFOA, PFNA) and identify whether rejection "
            "increases, decreases, or is non-monotonic with chain length. Cite at "
            "least one DOI per PFAS."
        ),
        "expected_pfas": None,
        "expected_membrane": "NF270",
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Cross-PFAS comparison + trend analysis. Agent must run multiple "
                  "filter queries (one per PFAS) then synthesize a trend statement."),
    },
    {
        "id": "agentic_pareto_front_PFOS",
        "category": "agentic_required",
        "user_query": (
            "For PFOS, identify all polyamide membranes that lie on the Pareto front "
            "in (water permeance A, water-PFAS selectivity A/B) space - i.e., no "
            "other membrane has BOTH higher A and higher A/B simultaneously. List the "
            "Pareto-front membranes with their A and A/B values."
        ),
        "expected_pfas": "PFOS",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Pareto-front computation: requires retrieving all (A, A/B) pairs "
                  "and applying dominance test. Agent should fetch the full set and "
                  "reason explicitly about non-domination - pure SQL is awkward."),
    },
    {
        "id": "agentic_maximin_PFOS_PFOA_PFHxA",
        "category": "agentic_required",
        "user_query": (
            "Find the single polyamide membrane whose WORST-CASE rejection across "
            "PFOS, PFOA, and PFHxA is the highest (i.e., maximize the minimum "
            "rejection across these 3 PFAS). Report the membrane, its rejection on "
            "each of the 3 PFAS, and which PFAS is the binding (worst) one."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Maximin optimization across multiple PFAS. Agent must retrieve "
                  "rejection per (membrane, PFAS) for all 3 PFAS, intersect membranes "
                  "across them, then compute min(rejection) per membrane and pick max."),
    },
    {
        "id": "agentic_min_pressure_PFOA_NF270",
        "category": "agentic_required",
        "user_query": (
            "For NF270 / PFOA, what is the LOWEST operating pressure (in psi) at "
            "which the membrane still achieves at least 90% PFOA rejection? Cite "
            "the source DOI for the supporting record(s)."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": "NF270",
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Conditional-on-threshold extremum. Agent must filter records by "
                  "the rejection threshold, then find the minimum pressure among "
                  "the survivors. Can be one SQL but agent should call cite_papers "
                  "for the matching record."),
    },
    {
        "id": "agentic_short_to_long_chain_correlation",
        "category": "agentic_required",
        "user_query": (
            "Test the hypothesis: if a polyamide membrane performs well on PFBA "
            "(short-chain), it should also perform well on PFOA (long-chain). For "
            "at least 3 commercial membranes that have been tested on BOTH, report "
            "the per-membrane PFBA rejection and PFOA rejection side by side, then "
            "state whether the hypothesis is supported (positive correlation), "
            "contradicted (negative or no correlation), or inconclusive."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Membrane-intersection across two PFAS + correlation reasoning. "
                  "Agent must filter twice, find the membranes appearing in both "
                  "result sets, then synthesize a comparative claim."),
    },
    {
        "id": "agentic_research_gap",
        "category": "agentic_required",
        "user_query": (
            "Identify the PFAS species in the dataset with the FEWEST distinct "
            "membrane studies. List which membranes have been tested on it, the "
            "total number of records, and recommend a research direction to "
            "address this gap (e.g., which membrane class is most under-studied "
            "for this PFAS)."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Cross-PFAS coverage analysis. Agent must compute distinct "
                  "membrane count per PFAS, sort, then drill down on the bottom one. "
                  "Two-pass aggregation."),
    },
    {
        "id": "agentic_default_membrane_recommendation",
        "category": "agentic_required",
        "user_query": (
            "If a user has no specific PFAS in mind and just wants a general-purpose "
            "commercial polyamide membrane for PFAS removal research, recommend the "
            "single membrane that has been most extensively characterized - i.e., "
            "tested across the largest number of distinct PFAS species. Report the "
            "membrane name, the number of distinct PFAS it covers, and its mean "
            "rejection across those PFAS."
        ),
        "expected_pfas": None,
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Coverage-breadth ranking. Agent must compute (membrane, "
                  "n_distinct_PFAS) cross-tab, then for the winner re-aggregate "
                  "rejection across its PFAS coverage."),
    },
    {
        "id": "agentic_high_concentration_PFOA",
        "category": "agentic_required",
        "user_query": (
            "Among PFOA studies that used a high initial PFAS concentration "
            "(> 1000 ng/L, simulating contaminated source water rather than dilute "
            "drinking water), which polyamide membrane shows the best mean rejection? "
            "Report the membrane, the mean rejection, the number of high-concentration "
            "records, and cite the source DOIs."
        ),
        "expected_pfas": "PFOA",
        "expected_membrane": None,
        "expected_refusal": False,
        "complexity_bin": "agentic",
        "notes": ("Conditional retrieval on a continuous experimental parameter "
                  "(init_conc_ngl). Agent must filter on concentration first, then "
                  "rank survivors by rejection."),
    },
]

# Combined benchmark
# OOD/adversarial prompts are intentionally excluded from ALL_PROMPTS:
# vanilla LLM has no access to the database, so prompts that test
# "refuse because the answer isn't in our specific dataset" (out-of-scope
# contaminant, unsupported technology, dataset-aggregate counts, etc.) are
# structurally unfair to it. The OOD_PROMPTS list is preserved above for
# reference / future stratified analysis but is not part of the headline
# benchmark.
ALL_PROMPTS = (LOOKUP_PROMPTS + MULTI_OBJ_PROMPTS
               + RECOMMEND_PROMPTS + AGENTIC_PROMPTS)

def get_prompts(category: str | None = None) -> list[dict]:
    """Return prompts, optionally filtered by category."""
    if category is None:
        return list(ALL_PROMPTS)
    return [p for p in ALL_PROMPTS if p["category"] == category]

if __name__ == "__main__":
    print(f"Total prompts: {len(ALL_PROMPTS)}")
    for cat in ("lookup", "multi_objective", "recommendation", "agentic_required"):
        print(f"  {cat}: {len(get_prompts(cat))}")
