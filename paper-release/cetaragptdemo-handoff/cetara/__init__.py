"""CetaraGPT redesign - code modules.

Layout:
    build_db   - Excel -> SQLite + pre-computed upper bounds
    tools      - 4 typed LangChain tools over the SQLite backend
    rungs      - Rungs 1-4 (vanilla / stuffed / text-to-SQL / agentic-RAG)
    grading    - Multi-metric grader (Jaccard, citation acc, hallucination, refusal)
    prompts    - Medium-scope benchmark (~30 prompts)
"""
