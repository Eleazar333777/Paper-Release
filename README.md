# PFAS Membrane Database and AI Research Platform
## Reproducibility Guide for Manuscript Reviewers

This document is a step-by-step reproducibility guide. It is written for academic reviewers and researchers who wish to evaluate the software and data described in the associated manuscript. No prior familiarity with this codebase is assumed.

Read this guide from top to bottom. Complete each section before proceeding to the next.

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Reviewer Quick Start](#2-reviewer-quick-start)
3. [Repository Structure](#3-repository-structure)
4. [System Requirements](#4-system-requirements)
5. [PostgreSQL Setup](#5-postgresql-setup)
6. [Data Import Procedure](#6-data-import-procedure)
7. [Website Setup](#7-website-setup)
8. [Website Verification](#8-website-verification)
9. [Gemini API Setup](#9-gemini-api-setup)
10. [AI Backend Setup](#10-ai-backend-setup)
11. [AI Backend Verification](#11-ai-backend-verification)
12. [Experimental Configurations](#12-experimental-configurations)
13. [How to Access ECI and Structured RAG](#13-how-to-access-eci-and-structured-rag)
14. [Troubleshooting](#14-troubleshooting)
15. [Known Limitations](#15-known-limitations)

---

## 1. Project Overview

This repository accompanies a manuscript on AI-assisted querying of PFAS membrane removal data. It contains two independent systems:

**System 1 — PFAS Database Website.** A Node.js/Express web application backed by PostgreSQL. It provides a searchable, filterable interface to 1,017 PFAS membrane performance records drawn from the peer-reviewed literature.

**System 2 — AI Demonstration Backend.** A Python/Flask application that exposes four experimental AI retrieval configurations described in the manuscript. It uses Google's Gemini API and operates against a bundled SQLite database. This system is fully independent of the website and may be evaluated separately.

For manuscript review, the AI Demonstration Backend (System 2) is the primary artifact of interest. The Website (System 1) provides the data browsing interface and may be evaluated independently.

---

## 2. Reviewer Quick Start

If you want the fastest path to evaluating the AI system only, without standing up the website:

1. Complete [Section 4 — System Requirements](#4-system-requirements) (Python portion only).
2. Complete [Section 9 — Gemini API Setup](#9-gemini-api-setup).
3. Complete [Section 10 — AI Backend Setup](#10-ai-backend-setup).
4. Open `http://localhost:5000` in your browser.

The AI backend ships with a bundled SQLite database (`pfas_membrane.db`). You do **not** need PostgreSQL to evaluate the AI system.

To evaluate the full website with the data browser, complete all sections in order.

---

## 3. Repository Structure

After cloning or extracting the repository, the top-level layout is:

```
paper-release/
├── server.js                        # Node.js/Express website server
├── package.json                     # Node.js dependencies
├── research_data.json               # 1,017-record PFAS dataset (for PostgreSQL import)
├── pfasdata.json                    # Same dataset used by the website's JSON path
├── public/                          # Static HTML/CSS/JS served by the website
│   ├── index.html
│   ├── datatable.html
│   ├── datagraph.html
│   ├── ai.html
│   ├── ai-expt.html
│   ├── gptdemo.html
│   └── ...
├── routes/
│   ├── adminserver.js
│   └── userDataAdmin.js
└── cetaragptdemo-handoff/           # AI demonstration backend (independent system)
    ├── demo_server.py               # Flask server — entry point
    ├── requirements.txt             # Python dependencies
    ├── pfas_membrane.db             # Bundled SQLite database (1,017 records)
    ├── gptdemo.html                 # Demo frontend served by Flask
    └── cetara/
        ├── __init__.py
        ├── rungs.py                 # Four experimental configurations
        ├── tools.py                 # Agentic RAG tool definitions
        ├── prompts.py               # Prompt templates
        ├── grading.py               # Evaluation utilities
        └── build_db.py              # Database construction utilities
```

The two systems share the same underlying dataset but use different database engines:

- The **website** reads from PostgreSQL (imported from `research_data.json`).
- The **AI backend** reads from the bundled SQLite file `pfas_membrane.db`.

---

## 4. System Requirements

### 4.1 Website Requirements

| Requirement | Minimum Version |
|---|---|
| Node.js | 18.x or later |
| npm | Bundled with Node.js 18+ |
| PostgreSQL | 14 or later |

**To check whether Node.js is installed:**

Open a terminal and run:

```bash
node --version
```

You should see output like `v18.19.0` or higher. If you see `command not found`, install Node.js from [https://nodejs.org](https://nodejs.org). Download the LTS release.

**To check whether PostgreSQL is installed:**

```bash
psql --version
```

You should see output like `psql (PostgreSQL) 14.x`. If not, install PostgreSQL from [https://www.postgresql.org/download/](https://www.postgresql.org/download/).

---

### 4.2 AI Backend Requirements

| Requirement | Minimum Version |
|---|---|
| Python | 3.10 or later |
| pip | Bundled with Python 3.10+ |
| A Google Gemini API key | See Section 9 |

**To check whether Python is installed:**

```bash
python3 --version
```

You should see `Python 3.10.x` or higher. If not, install from [https://www.python.org/downloads/](https://www.python.org/downloads/).

---

## 5. PostgreSQL Setup

> **Skip this section if you are only evaluating the AI demonstration backend.**

### 5.1 Start the PostgreSQL Service

On **macOS** (using Homebrew):

```bash
brew services start postgresql
```

On **Ubuntu/Debian**:

```bash
sudo service postgresql start
```

On **Windows**, PostgreSQL runs as a Windows Service and should start automatically. You can manage it via the Services control panel or pgAdmin.

### 5.2 Create the Database

Open a terminal and run:

```bash
createdb pfasdb
```

If `createdb` requires a username, run:

```bash
createdb -U postgres pfasdb
```

**Expected output:** No output means success. You may see a line like `CREATE DATABASE` if you used `psql` directly.

**If you see `database "pfasdb" already exists`:** That is acceptable. Continue to the next step.

**If you see a connection error:** Ensure the PostgreSQL service is running (see Step 5.1).

### 5.3 Verify the Database Was Created

```bash
psql -U postgres -c "\l" | grep pfasdb
```

You should see a line containing `pfasdb` in the output. If the line is not present, repeat Step 5.2.

---

## 6. Data Import Procedure

> **Skip this section if you are only evaluating the AI demonstration backend.**

The website requires two tables in PostgreSQL: `research_data` and `membranes`. There is no automated import script included in this repository. Follow the steps below exactly.

### 6.1 Connect to the Database

```bash
psql -U postgres -d pfasdb
```

You should see the `psql` prompt:

```
pfasdb=#
```

All commands in Sections 6.2–6.5 are entered at this prompt.

### 6.2 Create the `research_data` Table

At the `pfasdb=#` prompt, paste the following SQL exactly:

```sql
CREATE TABLE research_data (
    id                   INTEGER,
    membrane             TEXT,
    mwco_da              TEXT,
    pfas                 TEXT,
    removal_rate         TEXT,
    isoelectric_point    TEXT,
    water_contact_angle  TEXT,
    initial_concentration TEXT,
    is_mm                TEXT,
    pressure             TEXT,
    ph                   TEXT,
    doi                  TEXT,
    type                 TEXT,
    water_permeability   TEXT,
    a_water_permeance    TEXT,
    a_b                  TEXT,
    b_solute_permeance   TEXT,
    f                    DOUBLE PRECISION
);
```

**Expected output:**

```
CREATE TABLE
```

If you see an error like `relation "research_data" already exists`, the table was created previously. You may drop it and re-create it with `DROP TABLE research_data;` followed by the CREATE statement above.

### 6.3 Import Records from `research_data.json`

The dataset is stored as a JSON array in `research_data.json` at the top level of `paper-release/`. Import it using the following Python script. 

In a **new terminal** (not the psql prompt), navigate to the `paper-release/` directory:

```bash
cd paper-release
```

Then run:

```bash
python3 -c "
import json, psycopg2

with open('research_data.json') as f:
    records = json.load(f)

conn = psycopg2.connect('postgresql://postgres@localhost/pfasdb')
cur = conn.cursor()

for r in records:
    cur.execute('''
        INSERT INTO research_data
        (id, membrane, mwco_da, pfas, removal_rate, isoelectric_point,
         water_contact_angle, initial_concentration, is_mm, pressure, ph,
         doi, type, water_permeability, a_water_permeance, a_b,
         b_solute_permeance, f)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ''', (
        r.get('id'), r.get('membrane'), r.get('mwco_da'), r.get('pfas'),
        r.get('removal_rate'), r.get('isoelectric_point'), r.get('water_contact_angle'),
        r.get('initial_concentration'), r.get('is_mm'), r.get('pressure'), r.get('ph'),
        r.get('doi'), r.get('type'), r.get('water_permeability'), r.get('a_water_permeance'),
        r.get('a_b'), r.get('b_solute_permeance'), r.get('f')
    ))

conn.commit()
cur.close()
conn.close()
print('Import complete.')
"
```

**If your PostgreSQL user is not `postgres`**, replace `postgres@localhost` in the connection string with your username.

**If psycopg2 is not installed**, install it first:

```bash
pip3 install psycopg2-binary
```

Then re-run the import command above.

**Expected output:**

```
Import complete.
```

Do not continue until you see this message.

### 6.4 Verify the Import

Return to (or reopen) the `psql` prompt:

```bash
psql -U postgres -d pfasdb
```

Run:

```sql
SELECT COUNT(*) FROM research_data;
```

**Expected output:**

```
 count
-------
  1017
(1 row)
```

If the count is 0 or lower than 1017, the import did not complete. Re-run Section 6.3.

### 6.5 Create the `membranes` Table

At the `pfasdb=#` prompt, run:

```sql
CREATE TABLE membranes (
    membrane_name TEXT PRIMARY KEY
);

INSERT INTO membranes (membrane_name)
SELECT DISTINCT membrane
FROM research_data
WHERE membrane IS NOT NULL;
```

**Expected output:**

```
CREATE TABLE
INSERT 0 NNN
```

where `NNN` is the number of distinct membrane names found in the dataset.

Verify:

```sql
SELECT COUNT(*) FROM membranes;
```

You should see a nonzero count. 

Type `\q` to exit the `psql` prompt.

---

## 7. Website Setup

> **Skip this section if you are only evaluating the AI demonstration backend.**

### 7.1 Navigate to the Project Directory

Open a terminal and navigate to the `paper-release/` directory:

```bash
cd paper-release
```

All commands in Section 7 must be run from this directory.

### 7.2 Install Node.js Dependencies

```bash
npm install
```

This will download all required packages into a `node_modules/` directory. This may take 1–3 minutes depending on network speed.

**Expected output:** A summary line at the end such as `added 312 packages in 45s`. There may be warnings about optional dependencies; these are normal and can be ignored.

**Do not continue if you see `npm ERR!` lines.** If you do, check that Node.js 18+ is installed (`node --version`) and that you are in the correct directory.

### 7.3 Create the Environment File

Create a file named `.env` in the `paper-release/` directory. You can do this in any text editor, or from the terminal:

```bash
touch .env
```

Open `.env` and add the following lines:

```env
PORT=3001
DATABASE_URL=postgresql://postgres@localhost:5432/pfasdb
JWT_SECRET=reviewersecret
```

**Adjust the `DATABASE_URL`** if your PostgreSQL installation uses a different username or password. The general format is:

```
postgresql://USERNAME:PASSWORD@localhost:5432/pfasdb
```

If there is no password (common in local development installations), omit the `:PASSWORD` portion:

```
postgresql://postgres@localhost:5432/pfasdb
```

The `OPENAI_API_KEY` field is **not required** for manuscript review. The website's primary research data functionality does not use OpenAI.

Save the file before proceeding.

### 7.4 Start the Website Server

```bash
node server.js
```

**Expected output** (within a few seconds):

```
Server running on port 3001
🔍 Loaded membranes: [ 'NF90', 'NF270', ... ]
```

The membranes list printed confirms the PostgreSQL connection is working and the `membranes` table was found.

**If you see an error like `Error: connect ECONNREFUSED 127.0.0.1:5432`:** PostgreSQL is not running. Return to Section 5.1 and start the service.

**If you see `relation "membranes" does not exist`:** The table was not created. Return to Section 6.5.

Leave this terminal running. Do not close it while using the website.

---

## 8. Website Verification

With the server running (Section 7.4), open a web browser and navigate to:

```
http://localhost:3001
```

You should see the PFAS Membrane Database homepage.

**To verify the research data is accessible:**

Navigate to:

```
http://localhost:3001/datatable.html
```

You should see a filterable table of PFAS membrane records. The record count should be 1,017.

Navigate to:

```
http://localhost:3001/datagraph.html
```

You should see interactive visualizations of membrane performance data.

**What reviewers do not need:**

- Login or account creation
- Administrative pages
- The `/submit.html` data submission form

These features are not relevant to manuscript evaluation and may be ignored.

---

## 9. Gemini API Setup

The AI demonstration backend requires a Google Gemini API key. This applies regardless of whether you are running the website.

### 9.1 Obtain a Gemini API Key

1. Go to [https://aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey).
2. Sign in with a Google account.
3. Click **Create API key**.
4. Copy the key. It will look like: `AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX`

The free tier of Google AI Studio provides sufficient quota for manuscript review. No billing is required.

### 9.2 Set the Environment Variable

Open a terminal. This must be the **same terminal** you will use to start the AI backend in Section 10.

On **macOS or Linux**:

```bash
export GOOGLE_API_KEY=AIzaSyYOUR_ACTUAL_KEY_HERE
```

Replace `AIzaSyYOUR_ACTUAL_KEY_HERE` with your actual key.

On **Windows (Command Prompt)**:

```cmd
set GOOGLE_API_KEY=AIzaSyYOUR_ACTUAL_KEY_HERE
```

On **Windows (PowerShell)**:

```powershell
$env:GOOGLE_API_KEY="AIzaSyYOUR_ACTUAL_KEY_HERE"
```

**This variable is only set for the current terminal session.** If you close the terminal, you must set it again before restarting the server.

**Verify the variable is set** (macOS/Linux):

```bash
echo $GOOGLE_API_KEY
```

You should see your API key printed. If you see an empty line, the variable was not set correctly. Repeat the export command.

---

## 10. AI Backend Setup

### 10.1 Navigate to the Backend Directory

Open a terminal (or use the same terminal where you set `GOOGLE_API_KEY` in Section 9).

Navigate to the `cetaragptdemo-handoff/` directory:

```bash
cd paper-release/cetaragptdemo-handoff
```

All commands in Section 10 must be run from this directory.

### 10.2 Create a Python Virtual Environment

```bash
python3 -m venv venv
```

**Expected output:** No output, or a brief progress message. A new `venv/` directory is created.

Activate the virtual environment:

On **macOS or Linux**:

```bash
source venv/bin/activate
```

On **Windows (Command Prompt)**:

```cmd
venv\Scripts\activate
```

On **Windows (PowerShell)**:

```powershell
venv\Scripts\Activate.ps1
```

**Expected result:** Your terminal prompt will change to show `(venv)` at the beginning, like:

```
(venv) $
```

Do not proceed without activating the virtual environment.

### 10.3 Install Python Dependencies

The `requirements.txt` file lists the LangChain/LangGraph dependencies. The Flask web framework must be installed separately as it is not listed in `requirements.txt`:

```bash
pip install -r requirements.txt
pip install flask flask-limiter
```

Wait for both commands to complete successfully.

**Expected output** from the first command: A long list of packages being downloaded and installed, ending with:

```
Successfully installed langchain-... langchain-core-... ...
```

**Expected output** from the second command:

```
Successfully installed flask-... flask-limiter-... ...
```

**If you see dependency conflicts or errors:** Try upgrading pip first:

```bash
pip install --upgrade pip
```

Then re-run both install commands.

### 10.4 Verify the API Key Is Available

Before starting the server, confirm the environment variable is still set:

On **macOS or Linux**:

```bash
echo $GOOGLE_API_KEY
```

You should see your API key. If the line is empty, re-run the `export` command from Section 9.2.

### 10.5 Start the AI Backend Server

Confirm you are in the `cetaragptdemo-handoff/` directory and your virtual environment is active, then run:

```bash
python demo_server.py
```

**Expected output:**

```
============================================================
  CetaraGPT chatbot demo
  Model:    gemini-3.1-flash-lite
  DB:       pfas_membrane.db
  Tools:    <list of agentic tools>
  Open:     http://localhost:5000/
============================================================
```

Leave this terminal running. Do not close it.

**If you see `RuntimeError: GEMINI_API_KEY not found`:** The server could not find your API key. This means either:
- The `GOOGLE_API_KEY` environment variable is not set in this terminal (re-run Section 9.2), or
- The variable was set in a different terminal session.

**If you see `ModuleNotFoundError: No module named 'flask'`:** Flask was not installed. Ensure your virtual environment is active (you should see `(venv)` in your prompt) and re-run `pip install flask flask-limiter`.

---

## 11. AI Backend Verification

With the server running (Section 10.5), open a web browser and navigate to:

```
http://localhost:5000
```

You should see the CetaraGPT demo interface. It displays two side-by-side panels: **Vanilla LLM** and **Agentic RAG**.

**To verify the system is functioning:**

Type the following query into the text input field and submit it:

```
What is the removal rate of PFOS by NF90?
```

**Expected behavior:**

- The **Vanilla LLM** panel will respond using only the model's pretraining knowledge (no database access).
- The **Agentic RAG** panel will show tool calls being executed in real time (database lookups), then produce a response citing specific records from the dataset.

The Agentic RAG response should cite a DOI and report specific numerical values from the database.

If both panels return responses, the system is functioning correctly.

**Provide Your Own API Key (BYOK):**

The demo interface includes a field to enter your own Gemini API key. If the server was started without a valid `GOOGLE_API_KEY`, you may enter your key directly in the UI. The key is used only for that request and is never stored.

---

## 12. Experimental Configurations

The manuscript evaluates four AI retrieval configurations. All four are fully implemented in:

```
paper-release/cetaragptdemo-handoff/cetara/rungs.py
```

The configurations are:

### Configuration 1 — Vanilla LLM

**Backend function:** `run_vanilla()`

No retrieval. No database access. The model answers using only its pretraining knowledge. This establishes the baseline for evaluating what the model "already knows" about PFAS membranes without grounding.

### Configuration 2 — ECI (Exhaustive Context Injection / Stuffed Context)

**Backend function:** `run_stuffed()`

The complete 1,017-record dataset is serialized and inserted into the prompt as a text block. The model receives the full database as context. This tests the limits of long-context window utilization.

### Configuration 3 — Structured RAG

**Backend function:** `run_text_to_sql()`

The model generates a SQL query from the user's natural language question. The query is executed against the SQLite database. The result rows are returned to the model, which synthesizes a final answer. This tests text-to-SQL generation accuracy.

### Configuration 4 — Agentic RAG

**Backend function:** `run_agentic_demo()`

A multi-step agent with access to typed retrieval tools (filter by PFAS, filter by membrane, retrieve performance metrics, etc.). The agent plans and executes multiple tool calls before synthesizing an answer. This is the primary proposed method in the manuscript.

---

## 13. How to Access ECI and Structured RAG

**The current demo frontend (`gptdemo.html`) exposes only Vanilla and Agentic RAG.**

ECI (Stuffed Context) and Structured RAG are fully implemented in the backend but are not wired to interface controls in the current release. Reviewers do not need to implement these methods — the code is complete. To invoke them, the routing logic in `demo_server.py` and the interface controls in `gptdemo.html` must be extended.

### Option A — Direct Python Invocation (No Frontend Changes Required)

This is the simplest method for a reviewer who wants to verify all four configurations described in the manuscript without modifying the frontend.

With the virtual environment active and from the `cetaragptdemo-handoff/` directory, run:

```bash
python3 -c "
import os
from cetara import rungs

KEY = os.environ['GOOGLE_API_KEY']
QUERY = 'What is the removal rate of PFOS by NF90?'
DB = 'pfas_membrane.db'
MODEL = 'gemini-3.1-flash-lite'

print('=== Vanilla LLM ===')
r = rungs.run_vanilla(
    QUERY,
    model_name=MODEL,
    api_key=KEY
)
print(r.response_text)
print('ERROR:', r.error)

print()
print('=== ECI (Stuffed Context) ===')
r = rungs.run_stuffed(
    QUERY,
    model_name=MODEL,
    api_key=KEY,
    db_path=DB
)
print(r.response_text)
print('ERROR:', r.error)

print()
print('=== Structured RAG (Text-to-SQL) ===')
r = rungs.run_text_to_sql(
    QUERY,
    model_name=MODEL,
    api_key=KEY,
    db_path=DB
)
print(r.response_text)
print('SQL:', r.sql_generated)
print('ERROR:', r.error)

print()
print('=== Agentic RAG ===')
r = rungs.run_agentic_demo(
    QUERY,
    model_name=MODEL,
    api_key=KEY,
    db_path=DB
)
print(r.response_text)
print('ERROR:', r.error)
"
```

Successful execution should:

1. Produce four separate responses.
2. Show progressively more dataset-grounded behavior as retrieval sophistication increases.
3. End each section with:

```text
ERROR: None
```

This verifies that all four experimental configurations described in the manuscript are present and operational in the released artifact.

### Option B — Extend the Backend Routing

To expose ECI and Structured RAG through the web interface, two changes are required:

**Change 1: `demo_server.py` — accept the new rung values**

Locate the following lines (approximately line 444):

```python
rung    = (data.get("rung")     or "agentic").strip().lower()
...
if rung not in ("agentic", "vanilla"):
    return jsonify({"error": f"Unknown rung: {rung!r}"}), 400
```

Change the validation to:

```python
if rung not in ("agentic", "vanilla", "stuffed", "text_to_sql"):
    return jsonify({"error": f"Unknown rung: {rung!r}"}), 400
```

Then locate the `_run_agent_job` function (approximately line 284) and add branches for the new rungs in the `if/else` block:

```python
if rung == "vanilla":
    result = rungs.run_vanilla(query, model_name=MODEL, api_key=effective_key)
elif rung == "stuffed":
    result = rungs.run_stuffed(query, model_name=MODEL, api_key=effective_key, db_path=DB_PATH)
elif rung == "text_to_sql":
    result = rungs.run_text_to_sql(query, model_name=MODEL, api_key=effective_key, db_path=DB_PATH)
else:  # "agentic"
    with _RUN_LOCK:
        tools_mod.reset_call_log()
        result = rungs.run_agentic_demo(query, model_name=MODEL, api_key=effective_key, db_path=DB_PATH)
```

**Change 2: `gptdemo.html` — add selector controls**

Locate the constant near the top of the `<script>` section:

```javascript
const RUNGS_TO_SHOW = ["vanilla", "agentic"];
```

Change it to include the desired rungs:

```javascript
const RUNGS_TO_SHOW = ["vanilla", "stuffed", "text_to_sql", "agentic"];
```

Then add a dropdown or radio button group that sets the `rung` parameter when calling `/api/chat_start`. The request body format is:

```json
{
  "message": "your question here",
  "rung": "stuffed"
}
```

After making both changes, restart the demo server (Ctrl+C and re-run `python demo_server.py`) and reload the browser.

---

## 14. Troubleshooting

### The website shows no data in the table

**Likely cause:** The `research_data` table is empty or the PostgreSQL connection failed.

**Steps:**
1. Verify PostgreSQL is running: `psql -U postgres -c "SELECT 1;"`
2. Verify the import: `psql -U postgres -d pfasdb -c "SELECT COUNT(*) FROM research_data;"`
3. Verify the `DATABASE_URL` in `.env` is correct and matches your PostgreSQL credentials.
4. Restart the Node.js server after editing `.env`.

### The website server exits immediately with a PostgreSQL error

**Likely cause:** The `DATABASE_URL` is wrong or PostgreSQL is not running.

Check the exact error message in the terminal. Common messages:

- `connect ECONNREFUSED` → PostgreSQL is not running. Start it (Section 5.1).
- `password authentication failed` → The username or password in `DATABASE_URL` is wrong. Edit `.env`.
- `database "pfasdb" does not exist` → Run `createdb pfasdb` (Section 5.2).

### The AI backend exits with `ModuleNotFoundError`

**Likely cause:** The virtual environment is not active, or `pip install` was not run.

Activate the virtual environment:

```bash
source venv/bin/activate   # macOS/Linux
```

Then install dependencies again:

```bash
pip install -r requirements.txt
pip install flask flask-limiter
```

### The AI backend starts but queries return an error about the API key

**Likely cause:** The `GOOGLE_API_KEY` environment variable is empty or malformed.

Verify: `echo $GOOGLE_API_KEY`

If empty, re-run: `export GOOGLE_API_KEY=AIzaSy...`

If set but queries still fail, verify the key is valid by testing it at [https://aistudio.google.com](https://aistudio.google.com).

### The AI backend starts but queries time out or return no response

**Likely cause:** The Gemini free tier rate limit has been reached (15 requests/minute).

Wait 60 seconds and try again. For sustained evaluation, obtain an API key with a paid tier or spread queries over time.

### The `membranes` table error appears in the Node.js console

**Symptom:** `Failed to load membranes list: error: relation "membranes" does not exist`

**Fix:** Run the table creation SQL from Section 6.5.

---

## 15. Known Limitations

**ECI and Structured RAG are not exposed in the default frontend.** The demo interface ships with Vanilla and Agentic RAG only. ECI (`run_stuffed`) and Structured RAG (`run_text_to_sql`) are implemented in the backend and can be accessed via direct Python invocation (Section 13, Option A) or by extending the routing logic (Section 13, Option B).

**Flask and flask-limiter are not listed in `requirements.txt`.** These packages are required by `demo_server.py` but are absent from the provided requirements file. Reviewers must install them separately as described in Section 10.3.

**The Node.js server requires OpenAI credentials for some routes.** The `.env` file does not require `OPENAI_API_KEY` for basic data browsing functionality, but some internal routes will log errors if this key is absent. These errors do not affect the research data tables or the AI demonstration system, which uses Gemini rather than OpenAI.

**The Gemini model name may change.** The backend currently specifies `gemini-3.1-flash-lite` (set at the top of `demo_server.py` as the `MODEL` constant). If this model is deprecated or renamed by Google, update the `MODEL` constant accordingly. Available model names can be found at [https://ai.google.dev/gemini-api/docs/models](https://ai.google.dev/gemini-api/docs/models).

**User authentication is not required for review.** Administrative login, account creation, and data submission features exist in the website but are not necessary for evaluating the research contributions. Reviewers may ignore all authentication-related pages.

**The AI backend is designed for single-user demo use.** The Flask server serializes agentic runs via a global lock (`_RUN_LOCK`) because the tool call log (`CALL_LOG`) is module-global. Concurrent agentic queries from multiple browser tabs may queue. Vanilla queries are not subject to this constraint.

---

## Citation

If you use this software or dataset in your work, please cite the associated publication. Citation information will be provided upon manuscript acceptance.

---

## Contact

Questions about the dataset, software, or manuscript should be directed to the corresponding authors listed in the manuscript.
