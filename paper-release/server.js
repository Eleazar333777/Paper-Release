require("dotenv").config();
const express = require("express");
const bcrypt = require("bcryptjs");
const jwt = require("jsonwebtoken");
const { Pool } = require("pg");
const cors = require("cors");
const path = require("path");
const bodyParser = require('body-parser');
const axios = require('axios');
const use = require('@tensorflow-models/universal-sentence-encoder');
require('@tensorflow/tfjs');

const app = express();
const adminRouter = require('./routes/adminserver');
const port = process.env.PORT || 3001;

const CANDIDATE_MODELS = ["gpt-5.2"];

// Open AI assistant ID
const ASSISTANT_ID = process.env.OPENAI_ASSISTANT_ID;

//The OpenAI API Key
const fs = require("fs");
const OpenAI = require("openai");
const openaiClient = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
// Where your JSON DB lives
const DB_PATH = process.env.PFAS_DB_PATH || path.join(__dirname, "pfasdata.json");


// === OpenAI chat (no vector store): context-stuff whole JSON DB + user-only history ===
const DEFAULT_OPENAI_MODEL = process.env.OPENAI_MODEL || "gpt-5.2";

// In-memory conversations: convoId -> { userQuestions: [], modelUsed }
const openaiConvos = new Map();

// Build the single-string input exactly like the Quickstart, but with:
// - the entire DB (as text)
// - a "Past questions" header with user-only history
function buildInputText(dbText, pastQuestions, question) {
  const pastBlock = (pastQuestions && pastQuestions.length)
    ? `Past questions:\n${pastQuestions.map(q => `- ${q}`).join("\n")}\n\n`
    : "";

  return `
=== PFAS DATABASE (verbatim) ===
${dbText}

=== USER INPUT ===
${pastBlock}Current question: ${question}

=== INSTRUCTIONS ===
 You are a PFAS membrane assistant. You must work strictly as a database lookup and simple calculator on the table that follows (the "database").
GENERAL RULES
Use ONLY the rows and columns of this database. Do not use any external knowledge or assumptions, even if you think you know the answer from outside.


Whenever you mention a numerical value, copy it exactly from the database row you are using, except for the following formatting rule:


When you report a_water_permeance, b_solute_permeance, a_b or removal_rate in your answer, you must round them to two decimal places (e.g., 12.34).


For all other numerical values, do not approximate or invent new numbers.


Always use the full‑precision values from the database internally for any comparisons, filtering, or ranking.


Preferred units:


Pressure: use psi (from the "pressure" column).


Concentration: use ng/L (from the "initial_concentration" column).


pH: use the plain pH value (from the "ph" column).


Cite DOIs inline exactly as they appear in the "doi" column for the row(s) whose data you are using (for example: https://...).


When you decide that a particular row is important for the answer, try to report as many of that row's fields as are relevant, for example:


membrane, type, pfas,


a_water_permeance, b_solute_permeance, a_b, removal_rate,


pressure, ph, initial_concentration, is_mm,


mwco_da, doi.
 Do not be shallow if more relevant fields are available.


Do not have any preference for commercial or non‑commercial membranes, except where the explicit ranking rules below require you to separate them.


If the data cannot strictly meet the requested thresholds (for example, rejection, pressure, pH), say so explicitly and then give the closest options you can find and explain how they fall short.


Do not display the numeric value of f in your answer.


You may use f internally to rank membranes.


You may describe a membrane qualitatively (e.g., “this membrane has the highest f‑score among the options”), but you must not print the numeric f value.


DATABASE STRUCTURE
 You have a single table with at least the following columns (column names are exact):
membrane


type


water_permeability


a_water_permeance


b_solute_permeance


a_b


pfas


removal_rate


pressure


ph


initial_concentration


is_mm


mwco_da


doi
 and other fields as present.


STRICT FILTERING RULES (VERY IMPORTANT)
 You must treat the "pfas" and "membrane" columns as strict keys when answering questions.
When the user asks about a specific PFAS (for example "GenX"):


First filter the database to rows where pfas exactly equals that name (pfas == "GenX").


Ignore all rows whose pfas is anything else.


Do NOT treat different PFAS as interchangeable or similar.


When the user asks about a specific membrane (for example "NF270"):


Further filter to rows where the membrane exactly equals that string (membrane == "NF270").


Do NOT include data from any other membrane.


When the question refers to more than one PFAS or more than one membrane:


Build the answer from the union of the relevant filtered subsets, but NEVER mix in rows whose pfas or membrane are not explicitly requested.


If, after applying these filters, no rows remain:


Clearly state that the database has no entries for that PFAS / membrane combination.


Do NOT guess or invent values.


TASK TYPE 1 - TOP MEMBRANES FOR A SINGLE PFAS USING f‑SCORE
Trigger: The user asks you to recommend or select one or several membranes for a single PFAS, without an explicit multi‑PFAS comparison. Example:
"Recommend the top 3 commercial and top 3 non‑commercial membranes for GenX removal, balancing water permeability and selectivity."
Your primary objective in this case is:
 For the given PFAS, first look at ALL rows for that PFAS.  
Then, within the Commercial group, select the three membranes whose maximum f values are the highest;  
and within the Non‑commercial group, select the three membranes whose maximum f values are the highest.
Use the following exact procedure:
1. Identify the PFAS name in the question (for example "GenX") and apply the strict PFAS filter (pfas == "GenX"). Only use these rows for this task.
2. Split the filtered rows into two subsets based on "type":
   - Commercial subset: type == "Commercial".
   - Non‑commercial subset: type == "Non-commercial".
3. For EACH subset and for EACH unique membrane within that subset, you must first determine that membrane’s BEST f for this PFAS:
   a. Collect all rows with that exact combination (pfas, type, membrane).
   b. Within these rows, find the row with the highest "f" value (do not stop after looking at only one or two rows; check all rows for this membrane).
   c. Treat this row as the representative row for that membrane in this subset, and treat its f as that membrane’s f‑score for this PFAS and type.
   After this step, you should conceptually have a list like:
   - for each membrane in the Commercial subset: one row with its maximum f;
   - for each membrane in the Non‑commercial subset: one row with its maximum f.
4. For EACH subset separately (Commercial and Non‑commercial):
  a. Rank the membranes in that subset by their f‑scores in descending order (highest f first).  
   When ranking, you must compare all membranes in the subset, not just the first few that you see.
   b. If two or more membranes have exactly the same f‑score, break the tie by preferring the membrane with the higher "a_water_permeance".
   c. If there is still a tie after comparing "a_water_permeance", any order among the tied membranes is acceptable.
   A good way to think about this ranking step is:
    Imagine maintaining a “top‑3 list” of membranes by f for each subset.  
   Scan through the membranes one by one; if a membrane’s f is higher than the current lowest f in the top‑3 list, insert it into the list and drop the previous lowest.  
    Do not finalize the top‑3 list until you have considered every membrane in the subset.
5. In EACH subset, select the top three membranes by this ranking:
    If the subset has fewer than three membranes, report all available membranes and explicitly state that there are fewer than three.
6. In your answer, for each selected membrane in EACH subset, report at least:
    Membrane name and type.
    pfas.
 Do not print the numeric f‑score; instead, describe qualitatively that it was selected because it is among the highest‑f membranes in its group.
   The corresponding "a_water_permeance", "b_solute_permeance", “a_b” and "removal_rate" values, each rounded to two decimal places in your answer.
   The operating conditions ("pressure", "ph", "initial_concentration", "is_mm").
   Any other relevant fields available (for example, "mwco_da").
  The doi(s) corresponding to the row(s) that achieved that f‑score.
7. Do NOT include any membrane that is not in the top three for that subset by this ranking.
8. Do NOT include any rows for other PFAS in the answer to this type of question.

TASK TYPE 2 - MULTIPLE PFAS AND REJECTION‑CONSTRAINED DESIGN
 Trigger: The user asks you to design or compare treatment solutions involving two or more PFAS, typically with specific rejection targets and a desire to maximize water permeance. Example:
"I need to design a treatment solution for industrial wastewater containing high concentrations of both PFOS and GenX. The primary objective is a PFOS rejection of >95%, while the GenX rejection must be more than 97%. Under these conditions, I want to maximize water permeance. Please identify the membrane from the database that meet these criteria."


Use the following procedure:
Identify all PFAS names mentioned in the question and the rejection thresholds (on "removal_rate") for each PFAS, if given.


For EACH PFAS separately:
 a. Apply the PFAS filter (pfas == that compound).
 b. Within these rows, apply all rejection constraints from the question.
 c. If the question gives constraints on operating conditions (for example, pressure range, pH range), also apply those filters using the "pressure", "ph", etc.
 d. The remaining rows are candidate rows for that PFAS.


If the user wants a single membrane that works for several PFAS simultaneously:
 a. For each PFAS, note the set of candidate membrane names that satisfy the constraints.
 b. Take the intersection of these sets across PFAS; only membranes that appear in all sets can satisfy all constraints simultaneously.
 c. For each such membrane and each PFAS, identify the row(s) that satisfy the constraints and have the highest "a_water_permeance" for that PFAS.
 d. Use these "a_water_permeance" values to compare membranes.


To choose among candidate membranes, always maximize "a_water_permeance" subject to the given rejection constraints.


In your answer, clearly report:


Which membranes satisfy all given constraints.


For each such membrane and PFAS:


"a_water_permeance" and "removal_rate" (each rounded to two decimal places in your answer), and key operating conditions ("pressure", "ph", "initial_concentration", "is_mm").


The relevant doi(s).


If no membrane in the database satisfies all constraints simultaneously:


Explicitly state that no membrane meets all the requirements.


Then describe the closest options and explain how they fall short.


TASK TYPE 3 - REMOVAL RANGE FOR A PFAS‑MEMBRANE COMBINATION
 Trigger: The user asks about the removal (rejection) range for one specific PFAS and one specific membrane. Example:
"What is the removal range of PFOS by NF270?"


Use the following exact procedure:
Apply strict filtering:


First filter the database to rows where pfas equals the requested PFAS.


From those rows, further filter to rows where membrane equals the requested membrane.


If no rows remain after this filtering:


State that the database has no data for that PFAS‑membrane combination and stop.


If one or more rows remain:
 a. Consider the "removal_rate" column in this filtered subset.
 b. Find the minimum and maximum "removal_rate" values in this subset.
 c. Report the removal range as "min–max%", with both min and max rounded to two decimal places, and mention the number of rows that support this range.


Optionally, also describe how "removal_rate" varies with operating conditions:


For example, how it changes with "pressure", "ph", or "initial_concentration".


Provide doi(s) for at least the rows with the lowest and highest "removal_rate".


Do NOT use any "removal_rate" values from rows that do not match BOTH the pfas and the membrane specified in the question.


OTHER QUESTIONS
 If the question does not fit exactly into Task type 1, 2, or 3, you must still:
Apply the same strict pfas and membrane filtering rules.


Prefer using "a_water_permeance", "f", and "removal_rate" directly from the database to support your reasoning (but do not print numeric f values, and round "a_water_permeance" and "removal_rate" to two decimal places in your answer).


If the database does not contain enough information to answer exactly, say so clearly instead of guessing or using external knowledge.




`.trim();
}



// Database connection
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false },
});

// Middleware
app.use(express.json());
app.use(cors());
app.use(bodyParser.json());

//
//
//
//
//


//
//
//
//
// Non‐streaming Markdown‐only chat endpoint

// …listen, etc.

//TRAINED CHATBOT CALLS


// Serve index.html on root route
app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

const JWT_SECRET = process.env.JWT_SECRET;

const multer = require('multer');

// 1️⃣ Define where and how to store incoming files
const uploadDir = path.join(__dirname, 'uploads');
const storage   = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, uploadDir),
  filename:    (_req, file, cb) => {
    // Prepend a timestamp to avoid collisions
    const uniqueName = `${Date.now()}-${file.originalname}`;
    cb(null, uniqueName);
  }
});

// 2️⃣ Filter to allow only Excel files
const fileFilter = (_req, file, cb) => {
  const allowed = [
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel'
  ];
  cb(
    allowed.includes(file.mimetype)
      ? null
      : new Error('Only Excel files are allowed'),
    allowed.includes(file.mimetype)
  );
};

// 3️⃣ Create the Multer upload middleware
const upload = multer({
  storage,
  fileFilter,
  limits: { fileSize: 10 * 1024 * 1024 } // 10 MB max
});

// ─── Load membranes list once at startup ─────────────────────────────
let membraneList = [];

async function loadMembranes() {
  const client = await pool.connect();
  try {
    const { rows } = await client.query(
      // read from the new 'membranes' table you created
      `SELECT membrane_name
         FROM membranes
        ORDER BY LENGTH(membrane_name) DESC`
    );
    membraneList = rows.map(r => r.membrane_name);
    console.log("🔍 Loaded membranes:", membraneList);
  } finally {
    client.release();
  }
}

// Kick off the load (fire-and-forget)
loadMembranes().catch(err => {
  console.error("Failed to load membranes list:", err);
//   process.exit(1);  // optional: fail fast if this critical step errors
});


// User login
app.post("/login", async (req, res) => {
  const { username, password } = req.body;
  try {
    const result = await pool.query("SELECT * FROM users WHERE username = $1", [username]);
    if (result.rows.length === 0)
      return res.status(401).json({ error: "Invalid credentials" });

    const user = result.rows[0];
    const validPassword = await bcrypt.compare(password, user.password_hash);
    if (!validPassword)
      return res.status(401).json({ error: "Invalid credentials" });

    const token = jwt.sign({ userId: user.id }, JWT_SECRET, { });
    res.json({ token });
  } catch (error) {
    console.error("Login failed:", error);
    res.status(500).json({ error: "Login failed" });
  }
});

// JWT verification middleware
const authenticateToken = (req, res, next) => {
  const authHeader = req.header("Authorization");
  if (!authHeader) return res.status(401).json({ error: "Access denied: No token provided." });
  const token = authHeader.split(' ')[1];
  jwt.verify(token, JWT_SECRET, (err, user) => {
    if (err) return res.status(403).json({ error: "Invalid token" });
    req.user = user;
    next();
  });
};

// --- create a small public router that only exposes safe read endpoints ---
const publicDataRouter = express.Router();

// public read-only listing
publicDataRouter.get('/', async (req, res) => {
  try {
    const result = await pool.query('SELECT * FROM research_data');
    // prevent caching by proxies if you want fresh reads (or set caching as appropriate)
    res.set('Cache-Control', 'no-cache, no-store, must-revalidate'); // optional
    res.json(result.rows);
  } catch (err) {
    console.error('Failed to fetch public research data:', err);
    res.status(500).json({ error: 'Failed to fetch data' });
  }
});

app.use('/data', publicDataRouter);

const userDataAdminRouter = require('./routes/userDataAdmin');
app.use('/user-data', authenticateToken, userDataAdminRouter);

/**
 * POST /upload
 * - Requires a valid JWT (authenticateToken)
 * - Expects a single file under form field "excelFile"
 * - Saves file on disk, then records its metadata in user_uploads
 */
app.post(
  '/upload',
  authenticateToken,
  upload.single('excelFile'),
  async (req, res) => {
    try {
      // Multer places file info on req.file
      const { originalname, path: storedPath } = req.file;
      const userId = req.user.userId;      // from your JWT middleware

      // Record the upload in the database
      await pool.query(
        `INSERT INTO user_uploads (user_id, filename, stored_path)
         VALUES ($1, $2, $3)`,
        [userId, originalname, storedPath]
      );

      res.json({ success: true, message: 'File uploaded for review!' });
    } catch (err) {
      console.error('Upload error:', err);
      res.status(500).json({ success: false, error: err.message });
    }
  }
);



// PUBLIC CHAT ROUTE (Semantic Search + AI)
let useModel;
(async () => {
  console.log('🔄 Loading Universal Sentence Encoder...');
  useModel = await use.load();
  console.log('✅ USE model loaded.');
})();




// health check for your ping
app.get('/ping', (req, res) => {
  res.sendStatus(200);
});
// Protected route for raw research data
// app.get("/data", async (req, res) => {
//   try {
//     const result = await pool.query("SELECT * FROM research_data");
//     res.json(result.rows);
//   } catch (error) {
//     res.status(500).json({ error: "Failed to fetch data" });
//   }
// });

// ------------------------------------------------------------------
// Allow logged-in users to submit their own PFAS data
app.post("/user-data", authenticateToken, async (req, res) => {
  const userId = req.user.userId;  // JWT payload set in authenticateToken
  // Destructure all your fields from the request body
  const {
    membrane, mwco_da, pfas, removal_rate,
    isoelectric_point, water_contact_angle,
    mw, smiles, compound_size, log_kow,
    pka, initial_concentration, is_mm,
    pressure, ph, ref_id, ref, doi
  } = req.body;

  try {
    const result = await pool.query(
      `INSERT INTO user_data (
         user_id, membrane, mwco_da, pfas, removal_rate,
         isoelectric_point, water_contact_angle, mw, smiles,
         compound_size, log_kow, pka, initial_concentration,
         is_mm, pressure, ph, ref_id, ref, doi
       )
       VALUES (
         $1, $2, $3, $4, $5,
         $6, $7, $8, $9,
         $10, $11, $12, $13,
         $14, $15, $16, $17, $18, $19
       )
       RETURNING id, created_at`,
      [
        userId, membrane, mwco_da, pfas, removal_rate,
        isoelectric_point, water_contact_angle, mw, smiles,
        compound_size, log_kow, pka, initial_concentration,
        is_mm, pressure, ph, ref_id, ref, doi
      ]
    );
    res.status(201).json({ success: true, entry: result.rows[0] });
  } catch (err) {
    console.error("Error inserting user data:", err);
    res.status(500).json({ success: false, error: "Database error" });
  }
});


// User registration
app.post("/register", async (req, res) => {
  const { firstName, lastName, username, email, phone, institution, password } = req.body;
  if (!username || !password || !email || !firstName || !lastName || !phone) {
    return res.status(400).json({ error: "Missing required fields" });
  }
  try {
    const userExists = await pool.query("SELECT * FROM users WHERE username = $1", [username]);
    if (userExists.rows.length > 0) {
      return res.status(400).json({ error: "Username already taken" });
    }
    const hash = await bcrypt.hash(password, 10);
    await pool.query(
      `INSERT INTO users (first_name, last_name, username, email, phone, institution, password_hash) VALUES ($1,$2,$3,$4,$5,$6,$7)`,
      [firstName, lastName, username, email, phone, institution||'N/A', hash]
    );
    res.status(201).json({ message: "User registered successfully" });
  } catch (error) {
    console.error("Registration error:", error);
    res.status(500).json({ error: "Registration failed" });
  }
});

// Adding a single entry of data
app.post("/single_entries", async (req, res) => {
  const {
    membrane,
    mwco_da,
    pfas,
    removal_rate,
    isoelectric_point,
    water_contact_angle,
    mw,
    smiles,
    compound_size,
    log_kow,
    pka,
    initial_concentration,
    is_mm,
    pressure,
    ph,
    doi_reference
  } = req.body;

  // Basic validation (membrane, pfas, removal_rate are required)
  if (!membrane || !pfas || removal_rate == null) {
    return res.status(400).json({ success: false, error: 'Required fields missing.' });
  }
  try {
    const insertQuery = `
      INSERT INTO single_entries (
        membrane,
        mwco_da,
        pfas,
        removal_rate,
        isoelectric_point,
        water_contact_angle,
        mw,
        smiles,
        compound_size,
        log_kow,
        pka,
        initial_concentration,
        is_mm,
        pressure,
        ph,
        doi_reference
      ) VALUES (
        $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16
      )
      RETURNING id;
    `;

    const values = [
      membrane,
      mwco_da || null,
      pfas,
      removal_rate,
      isoelectric_point || null,
      water_contact_angle || null,
      mw || null,
      smiles || null,
      compound_size || null,
      log_kow || null,
      pka || null,
      initial_concentration || null,
      typeof is_mm === 'boolean' ? is_mm : null,
      pressure || null,
      ph || null,
      doi_reference || null
    ];

    const { rows } = await pool.query(insertQuery, values);
    const newId = rows[0].id;

    return res.status(201).json({
      success: true,
      message: `Entry created with ID ${newId}`,
      id: newId
    });
  } catch (err) {
    console.error('Error inserting single entry:', err);
    return res.status(500).json({
      success: false,
      error: 'Database error while inserting single entry.'
    });
  }

});
// OPENAI API CALLS

// Start a new conversation (no uploads, no vector store)
app.post("/api/openai-chat/start", async (req, res) => {
  try {
    const { model } = req.body || {};
    const convoId = `c_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    openaiConvos.set(convoId, {
      userQuestions: [],
      modelUsed: model || DEFAULT_OPENAI_MODEL
    });
    return res.json({ convoId, modelUsed: openaiConvos.get(convoId).modelUsed });
  } catch (err) {
    console.error("start (no-vs) error:", err);
    return res.status(500).json({ error: err.message });
  }
});

// Ask within an existing conversation: retrieve context each turn, prepend past user questions
// Ask within an existing conversation: stuff whole DB + past user questions each turn
app.use('/api/openai-chat/ask', (req, res, next) => {
  req.setTimeout(0);
  res.setTimeout(0);
  next();
});

// Ask within an existing conversation: stuff whole DB + past user questions each turn (with logging + timeout + model fallback)
// Ask within an existing conversation: whole-DB prompt + keep-alive trickle until done
// NEW: SSE "thinking phrases" route (no OpenAI streaming required)
app.get("/api/openai-chat/ask-sse", async (req, res) => {
  console.log("🎯 SSE ENDPOINT HIT!");

  const { convoId, q } = req.query || {};
  console.log("🔍 SSE Request Details:");
  console.log("  - convoId from query:", convoId);
  console.log("  - question:", q);
  console.log("  - openaiConvos size:", openaiConvos.size);
  console.log("  - All convo IDs:", Array.from(openaiConvos.keys()));
  console.log("  - Has this convo?", openaiConvos.has(convoId));
  
  // Helper to send named events
  const send = (event, dataObj) => {
    try {
      res.write(`event: ${event}\n`);
      res.write(`data: ${JSON.stringify(dataObj)}\n\n`);
    } catch (e) {
      console.error("Error writing SSE:", e);
    }
  };

  // Setup SSE headers first
  res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
  res.setHeader("Cache-Control", "no-cache, no-transform");
  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");
  res.flushHeaders?.();

  console.log("SSE called with:", { convoId, q, hasConvo: openaiConvos.has(convoId) });

  try {
    // Validate convoId
    if (!convoId || !openaiConvos.has(convoId)) {
      send("final", { error: "Invalid or missing conversation ID" });
      send("done", {});
      return res.end();
    }

    // Validate question
    const question = (q || "").trim();
    if (!question) {
      send("final", { error: "No question provided" });
      send("done", {});
      return res.end();
    }

    // Periodic "thinking" messages to keep connection alive
    const PHRASES = [
      "Reading database…",
      "Building prompt…",
      "Calling model…",
      "Thinking…",
      "Organizing citations…"
    ];
    let idx = 0;
    send("status", { message: "Starting…" });
    
    const ticker = setInterval(() => {
      send("status", { message: PHRASES[idx++ % PHRASES.length] });
    }, 5000);

    // Check DB file exists
    if (!fs.existsSync(DB_PATH)) {
      clearInterval(ticker);
      send("final", { error: `Database file not found at ${DB_PATH}` });
      send("done", {});
      return res.end();
    }

    const dbText = fs.readFileSync(DB_PATH, "utf8");
    const convo = openaiConvos.get(convoId);
    const input = buildInputText(dbText, convo.userQuestions.slice(-8), question);

    // Timeout wrapper
    const withTimeout = (p, ms) =>
      Promise.race([
        p,
        new Promise((_, rej) => 
          setTimeout(() => rej(new Error(`Timeout after ${ms}ms`)), ms)
        )
      ]);

    // Try models in order (use valid OpenAI model names)
    const modelsToTry = [convo.modelUsed, "gpt-5.2", "gpt-5.2"].filter(Boolean);

    let resp, usedModel, lastErr;
    for (const m of modelsToTry) {
      try {
        send("status", { message: `Calling ${m}…` });
        
        // NON-STREAMING OpenAI call - just wait for complete response
        resp = await withTimeout(
          openaiClient.responses.create({
            model: m,
        
            // 👇 SAME prompt text, just wrapped differently
            input: input,
        
            // 🧠 REASONING KNOB (THIS IS THE KEY)
            reasoning: {
              effort: "medium"   // "low" | "medium" | "high" | "xhigh"
            },
        
            // Optional but recommended
            text: {
              verbosity: "low"
            },
        
            //temperature: 0.3,
            max_output_tokens: 10000
          }),
          240000
        );
        
        
        usedModel = m;
        break;  // Success, exit loop
        
      } catch (e) {
        console.error(`Error with model ${m}:`, e.message);
        lastErr = e;
        // Continue to next model
      }
    }

    clearInterval(ticker);  // Stop the "thinking" messages

    if (!resp) {
      send("final", { 
        error: `All models failed. Last error: ${lastErr?.message || "Unknown error"}` 
      });
      send("done", {});
      return res.end();
    }

    // Extract the answer from OpenAI response
    const answer = resp.output_text?.trim() || "No response generated";

    
    // Track user history
    convo.userQuestions.push(question);

    // Send the complete answer at once
    send("final", { answer, modelUsed: usedModel || convo.modelUsed });
    send("done", {});
    res.end();

  } catch (err) {
    console.error("SSE endpoint error:", err);
    try {
      send("final", { error: `Server error: ${err.message}` });
      send("done", {});
    } catch {}
    res.end();
  }
});


// -------------------- Experimental prompt builder --------------------
// New prompt text to experiment with alternative instruction style.
// Keeps strict DB rules and filtering but changes the assistant behavior
// to be more exploratory / ask follow-ups / provide hypotheses, etc.
function buildInputTextExperiment(dbText, pastQuestions, question) {
    const pastBlock = (pastQuestions && pastQuestions.length)
      ? `Past questions:\n${pastQuestions.map(q => `- ${q}`).join("\n")}\n\n`
      : "";
  
    // NOTE: keep the database content the same but swap in an alternate INSTRUCTIONS block
    return `
  === PFAS DATABASE (verbatim) ===
  ${dbText}
  
  === USER INPUT ===
  ${pastBlock}Current question: ${question}
  
  === EXPERIMENTAL INSTRUCTIONS === You are an experimental PFAS research assistant. Use the database rows strictly as the primary source of truth, but you are allowed to: 1. State clearly when you're making an inference (label them "Inference:") and base them only on rows present in the database. 2. Propose up to 2 short, concrete follow-up questions the user could ask to clarify ambiguous requests. 3. When recommending membranes, list trade-offs concisely (e.g., permeability vs removal rate) and highlight any rows that narrowly miss filters. 4. Use numerical values from the database (do not invent numbers); round a_water_permeance, b_solute_permeance, a_b and removal_rate to two decimals when printing. Be sure when commenting on these quantities that you format them attractively (so not like b_solute_permeance, etc). 5. Cite DOIs exactly as they appear in the doi column for rows you used. 6. Use your websearch feature to get more background knowledge and more up-to-date knowledge about the subject. 7. Use your uploaded data base of research papers to assist with questions relating to the mechanisms behind membranes. Try to avoid huge tables; you can use tables, but please make them small.
  
  `.trim();
  }
  async function waitForRun(threadId, runId) {
    while (true) {
      const run = await openaiClient.beta.threads.runs.retrieve(threadId, runId);
  
      if (run.status === "completed") return run;
      if (["failed", "cancelled", "expired"].includes(run.status)) {
        throw new Error(`Run ended with status: ${run.status}`);
      }
  
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  
  function extractAssistantText(message) {
    if (!message?.content) return "";
    return message.content
      .map((part) => part?.text?.value || part?.text || "")
      .join("\n")
      .trim();
  }
  
  function splitIntoChunks(text, maxLen = 200000) {
    const chunks = [];
    for (let i = 0; i < text.length; i += maxLen) {
      chunks.push(text.slice(i, i + maxLen));
    }
    return chunks;
  }
  
  app.get("/api/openai-chat/ask-sse-expt", async (req, res) => {
    console.log("🎯 EXPERIMENTAL SSE ENDPOINT HIT!");
  
    const { convoId, q } = req.query || {};
  
    const send = (event, dataObj) => {
      try {
        res.write(`event: ${event}\n`);
        res.write(`data: ${JSON.stringify(dataObj)}\n\n`);
      } catch (e) {
        console.error("Error writing SSE (expt):", e);
      }
    };
  
    res.setHeader("Content-Type", "text/event-stream; charset=utf-8");
    res.setHeader("Cache-Control", "no-cache, no-transform");
    res.setHeader("Connection", "keep-alive");
    res.setHeader("X-Accel-Buffering", "no");
    res.flushHeaders?.();
  
    try {
      if (!convoId || !openaiConvos.has(convoId)) {
        send("final", { error: "Invalid or missing conversation ID" });
        send("done", {});
        return res.end();
      }
  
      if (!ASSISTANT_ID) {
        send("final", { error: "Missing OPENAI_ASSISTANT_ID env var" });
        send("done", {});
        return res.end();
      }
  
      const question = (q || "").trim();
      if (!question) {
        send("final", { error: "No question provided" });
        send("done", {});
        return res.end();
      }
  
      const PHRASES = [
        "Reading database…",
        "Applying experimental guidelines…",
        "Constructing alternative prompt…",
        "Calling assistant…",
        "Thinking about follow-up questions…"
      ];
  
      let idx = 0;
      send("status", { message: "Starting experimental run…" });
      const ticker = setInterval(() => {
        send("status", { message: PHRASES[idx++ % PHRASES.length] });
      }, 5000);
  
      if (!fs.existsSync(DB_PATH)) {
        clearInterval(ticker);
        send("final", { error: `Database file not found at ${DB_PATH}` });
        send("done", {});
        return res.end();
      }
  
      const dbText = fs.readFileSync(DB_PATH, "utf8");
      const convo = openaiConvos.get(convoId);
      const prompt = buildInputTextExperiment(dbText, convo.userQuestions.slice(-8), question);
  
      const withTimeout = (p, ms) =>
        Promise.race([
          p,
          new Promise((_, rej) => setTimeout(() => rej(new Error(`Timeout after ${ms}ms`)), ms))
        ]);
  
      // Step 1: Create thread
      send("status", { message: "Creating thread…" });
      const thread = await withTimeout(openaiClient.beta.threads.create({}), 240000);
      console.log("✅ Thread created:", thread.id);
  
      if (!thread?.id) {
        clearInterval(ticker);
        send("final", { error: "Thread created but no thread.id returned. Check openai package version." });
        send("done", {});
        return res.end();
      }
  
      // Step 2: Add prompt as message chunks
      send("status", { message: "Adding prompt chunks…" });
      const promptChunks = splitIntoChunks(prompt, 200000);
      for (const chunk of promptChunks) {
        await withTimeout(
          openaiClient.beta.threads.messages.create(thread.id, {
            role: "user",
            content: chunk
          }),
          240000
        );
      }
      console.log(`✅ Added ${promptChunks.length} chunk(s) to thread`);
  
      // Step 3: Create run — no temperature/top_p, they cause failures
      send("status", { message: "Running assistant…" });
      const run = await withTimeout(
        openaiClient.beta.threads.runs.create(thread.id, {
          assistant_id: ASSISTANT_ID,
          max_prompt_tokens: 100000,
          max_completion_tokens: 10000
        }),
        240000
      );
      console.log("✅ Run created:", run.id);
  
      if (!run?.id) {
        clearInterval(ticker);
        send("final", { error: "Run created but no run.id returned." });
        send("done", {});
        return res.end();
      }
  
      // Step 4: Poll until complete
      send("status", { message: "Waiting for assistant…" });
      let finalRun;
      while (true) {
        const polled = await withTimeout(
          openaiClient.beta.threads.runs.retrieve(thread.id, run.id),
          240000
        );
        console.log("🔄 Run status:", polled.status);
  
        if (polled.status === "completed") {
          finalRun = polled;
          break;
        }
        if (["failed", "cancelled", "expired"].includes(polled.status)) {
          clearInterval(ticker);
          send("final", { error: `Run ended with status: ${polled.status}. Last error: ${JSON.stringify(polled.last_error)}` });
          send("done", {});
          return res.end();
        }
        await new Promise(r => setTimeout(r, 1500));
      }
  
      // Step 5: Retrieve messages
      const messages = await withTimeout(
        openaiClient.beta.threads.messages.list(thread.id),
        240000
      );
  
      const assistantMsg = messages.data.find(m => m.role === "assistant");
      if (!assistantMsg) {
        clearInterval(ticker);
        send("final", { error: "Run completed but no assistant message found." });
        send("done", {});
        return res.end();
      }
  
      const answerText = extractAssistantText(assistantMsg) || "No response generated.";
      console.log("✅ Got answer, length:", answerText.length);
  
      clearInterval(ticker);
      convo.userQuestions.push(question);
  
      send("final", {
        answer: answerText,
        modelUsed: convo.modelUsed,
        tools_used: true,
        assistant_id: ASSISTANT_ID
      });
  
      send("done", {});
      return res.end();
  
    } catch (err) {
      console.error("❌ Experimental SSE error:", err);
      try {
        send("final", { error: `Server error: ${err.message}` });
        send("done", {});
      } catch {}
      return res.end();
    }
  });

  
// Serve static files
app.use(express.static(path.join(__dirname, "public")));

//app.listen(port, () => console.log(`Server running on port ${port}`));
// At the very end:
const server = app.listen(port, () => {
  console.log(`Server running on port ${port}`);
});

// Disable the default 2-minute timeout (or set it higher if you prefer)
server.timeout = 0;                    // no timeout
