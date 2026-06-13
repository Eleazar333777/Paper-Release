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
const port = process.env.PORT || 3002;

const CANDIDATE_MODELS = ["gpt-5.2"];

// Open AI assistant ID
const ASSISTANT_ID = process.env.OPENAI_ASSISTANT_ID;

//The OpenAI API Key
const OpenAI = require("openai");
const openaiClient = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

// === OpenAI chat (no vector store): context-stuff whole JSON DB + user-only history ===
const DEFAULT_OPENAI_MODEL = process.env.OPENAI_MODEL || "gpt-5.2";

// In-memory conversations: convoId -> { userQuestions: [], modelUsed }
const openaiConvos = new Map();

// Build the single-string input exactly like the Quickstart, but with:
// - the entire DB (as text)
// - a "Past questions" header with user-only history
function buildInputTextLiMg(dbText, pastQuestions, question) {
  const pastBlock = (pastQuestions && pastQuestions.length)
    ? `Past questions:\n${pastQuestions.map(q => `- ${q}`).join("\n")}\n\n`
    : "";

  return `
=== LI/MG DATABASE (verbatim) ===
${dbText}

=== USER INPUT ===
${pastBlock}Current question: ${question}

=== INSTRUCTIONS ===
You are a Li/Mg membrane assistant.
Use ONLY the rows and columns of this database.
Do not introduce membranes, DOIs, values, or rankings not present in those rows.
If the question asks for a ranking, only rank the rows provided.
Use membrane_normalized, not membrane, when referring to the membrane name.
Li rejection and Mg rejection are stored internally as fractions. Convert them to percentages when presenting them to the user.
Do not use external knowledge.
Do not invent numbers.
If the data cannot strictly satisfy the request, say so explicitly.
Cite DOI exactly as shown in the row.
Prefer concise answers.
`.trim();
}

function buildInputTextExperiment(dbText, pastQuestions, question) {
  const pastBlock = (pastQuestions && pastQuestions.length)
    ? `Past questions:\n${pastQuestions.map(q => `- ${q}`).join("\n")}\n\n`
    : "";

  return `
=== PFAS DATABASE (verbatim) ===
${dbText}

=== USER INPUT ===
${pastBlock}Current question: ${question}

=== EXPERIMENTAL INSTRUCTIONS === You are an experimental PFAS research assistant. Use the database rows strictly as the primary source of truth, but you are allowed to: 1. State clearly when you're making an inference (label them "Inference:") and base them only on rows present in the database. 2. Propose up to 2 short, concrete follow-up questions the user could ask to clarify ambiguous requests. 3. When recommending membranes, list trade-offs concisely (e.g., permeability vs removal rate) and highlight any rows that narrowly miss filters. 4. Use numerical values from the database (do not invent numbers); round a_water_permeance, b_solute_permeance, a_b and removal_rate to two decimals when printing. Be sure when commenting on these quantities that you format them attractively (so not like b_solute_permeance, etc). 5. Cite DOIs exactly as they appear in the doi column for rows you used. 6. Use your uploaded data base of research papers to assist with questions relating to the mechanisms behind membranes. Try to avoid huge tables; you can use tables, but please make them small.
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

// Serve index.html on root route
app.get("/", (req, res) => {
  res.sendFile(path.join(__dirname, "public", "index.html"));
});

const JWT_SECRET = process.env.JWT_SECRET;

const multer = require('multer');

// 1️⃣ Define where and how to store incoming files
const uploadDir = path.join(__dirname, 'uploads');
const storage = multer.diskStorage({
  destination: (_req, _file, cb) => cb(null, uploadDir),
  filename: (_req, file, cb) => {
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
    const { rows } = await client.query(`
      SELECT membrane_name
      FROM membranes
      ORDER BY LENGTH(membrane_name) DESC
    `);

    membraneList = rows.map(r => r.membrane_name);
    console.log("🔍 Loaded membranes:", membraneList);
  } finally {
    client.release();
  }
}

// Kick off the load (fire-and-forget)
loadMembranes().catch(err => {
  console.error("Failed to load membranes list:", err);
});

// User login
app.post("/login", async (req, res) => {
  const { username, password } = req.body;

  try {
    const result = await pool.query(
      "SELECT * FROM users WHERE username = $1",
      [username]
    );

    if (result.rows.length === 0) {
      return res.status(401).json({ error: "Invalid credentials" });
    }

    const user = result.rows[0];
    const validPassword = await bcrypt.compare(password, user.password_hash);

    if (!validPassword) {
      return res.status(401).json({ error: "Invalid credentials" });
    }

    const token = jwt.sign(
      { userId: user.id },
      JWT_SECRET,
      {}
    );

    res.json({ token });

  } catch (error) {
    console.error("Login failed:", error);
    res.status(500).json({ error: "Login failed" });
  }
});

// JWT verification middleware
const authenticateToken = (req, res, next) => {
  const authHeader = req.header("Authorization");

  if (!authHeader) {
    return res.status(401).json({
      error: "Access denied: No token provided."
    });
  }

  const token = authHeader.split(' ')[1];

  jwt.verify(token, JWT_SECRET, (err, user) => {
    if (err) {
      return res.status(403).json({ error: "Invalid token" });
    }

    req.user = user;
    next();
  });
};

// --- create a small public router that only exposes safe read endpoints ---
const publicDataRouter = express.Router();

// public read-only listing
publicDataRouter.get('/', async (req, res) => {
  try {
    const result = await pool.query('SELECT * FROM limg_data');

    res.set(
      'Cache-Control',
      'no-cache, no-store, must-revalidate'
    );

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
      const { originalname, path: storedPath } = req.file;
      const userId = req.user.userId;

      await pool.query(
        `
        INSERT INTO user_uploads (
          user_id,
          filename,
          stored_path
        )
        VALUES ($1, $2, $3)
        `,
        [userId, originalname, storedPath]
      );

      res.json({
        success: true,
        message: 'File uploaded for review!'
      });

    } catch (err) {
      console.error('Upload error:', err);

      res.status(500).json({
        success: false,
        error: err.message
      });
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

// Allow logged-in users to submit their own PFAS data
app.post("/user-data", authenticateToken, async (req, res) => {
  const userId = req.user.userId;

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
    ref_id,
    ref,
    doi
  } = req.body;

  try {
    const result = await pool.query(
      `
      INSERT INTO user_data (
        user_id,
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
        ref_id,
        ref,
        doi
      )
      VALUES (
        $1, $2, $3, $4, $5,
        $6, $7, $8, $9,
        $10, $11, $12, $13,
        $14, $15, $16, $17, $18, $19
      )
      RETURNING id, created_at
      `,
      [
        userId,
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
        ref_id,
        ref,
        doi
      ]
    );

    res.status(201).json({
      success: true,
      entry: result.rows[0]
    });

  } catch (err) {
    console.error("Error inserting user data:", err);

    res.status(500).json({
      success: false,
      error: "Database error"
    });
  }
});

// User registration
app.post("/register", async (req, res) => {
  const {
    firstName,
    lastName,
    username,
    email,
    phone,
    institution,
    password
  } = req.body;

  if (
    !username ||
    !password ||
    !email ||
    !firstName ||
    !lastName ||
    !phone
  ) {
    return res.status(400).json({
      error: "Missing required fields"
    });
  }

  try {
    const userExists = await pool.query(
      "SELECT * FROM users WHERE username = $1",
      [username]
    );

    if (userExists.rows.length > 0) {
      return res.status(400).json({
        error: "Username already taken"
      });
    }

    const hash = await bcrypt.hash(password, 10);

    await pool.query(
      `
      INSERT INTO users (
        first_name,
        last_name,
        username,
        email,
        phone,
        institution,
        password_hash
      )
      VALUES ($1,$2,$3,$4,$5,$6,$7)
      `,
      [
        firstName,
        lastName,
        username,
        email,
        phone,
        institution || 'N/A',
        hash
      ]
    );

    res.status(201).json({
      message: "User registered successfully"
    });

  } catch (error) {
    console.error("Registration error:", error);

    res.status(500).json({
      error: "Registration failed"
    });
  }
});

const withTimeout = (p, ms) =>
  Promise.race([
    p,
    new Promise((_, rej) =>
      setTimeout(() => rej(new Error(`Timeout after ${ms}ms`)), ms)
    )
  ]);

// Start a new conversation
const handleChatStart = async (req, res) => {
  try {
    const { model } = req.body || {};

    const convoId = `c_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;

    openaiConvos.set(convoId, {
      userQuestions: [],
      modelUsed: model || DEFAULT_OPENAI_MODEL
    });

    return res.json({
      convoId,
      modelUsed: openaiConvos.get(convoId).modelUsed
    });
  } catch (err) {
    console.error("start (no-vs) error:", err);
    return res.status(500).json({ error: err.message });
  }
};

app.post("/api/openai-chat/start", handleChatStart);
app.post("/api/limg-chat/start", handleChatStart);

app.use('/api/openai-chat/ask', (req, res, next) => {
  req.setTimeout(0);
  res.setTimeout(0);
  next();
});

// Main SSE route
app.get("/api/openai-chat/ask-sse", async (req, res) => {
  console.log("🎯 SSE ENDPOINT HIT!");

  const { convoId, q } = req.query || {};

  const send = (event, dataObj) => {
    try {
      res.write(`event: ${event}\n`);
      res.write(`data: ${JSON.stringify(dataObj)}\n\n`);
    } catch (e) {
      console.error("Error writing SSE:", e);
    }
  };

  res.setHeader(
    "Content-Type",
    "text/event-stream; charset=utf-8"
  );

  res.setHeader(
    "Cache-Control",
    "no-cache, no-transform"
  );

  res.setHeader("Connection", "keep-alive");
  res.setHeader("X-Accel-Buffering", "no");

  res.flushHeaders?.();

  try {
    if (!convoId || !openaiConvos.has(convoId)) {
      send("final", {
        error: "Invalid or missing conversation ID"
      });

      send("done", {});
      return res.end();
    }

    const question = (q || "").trim();

    if (!question) {
      send("final", {
        error: "No question provided"
      });

      send("done", {});
      return res.end();
    }

    const convo = openaiConvos.get(convoId);

    const dbText = await getLiMgContext(question);

    const input = buildInputTextLiMg(
      dbText,
      convo.userQuestions.slice(-8),
      question
    );

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
      send("status", {
        message: PHRASES[idx++ % PHRASES.length]
      });
    }, 5000);

    const modelsToTry = [
      convo.modelUsed,
      "gpt-5.2",
      "gpt-5.2"
    ].filter(Boolean);

    let resp, usedModel, lastErr;

    for (const m of modelsToTry) {
      try {
        send("status", {
          message: `Calling ${m}…`
        });

        resp = await withTimeout(
          openaiClient.responses.create({
            model: m,

            input: input,

            reasoning: {
              effort: "medium"
            },

            text: {
              verbosity: "low"
            },

            max_output_tokens: 10000
          }),
          240000
        );

        usedModel = m;
        break;

      } catch (e) {
        console.error(`Error with model ${m}:`, e.message);
        lastErr = e;
      }
    }

    clearInterval(ticker);

    if (!resp) {
      send("final", {
        error:
          `All models failed. Last error: ${lastErr?.message || "Unknown error"
          }`
      });

      send("done", {});
      return res.end();
    }

    const answer =
      resp.output_text?.trim() ||
      "No response generated";

    convo.userQuestions.push(question);

    send("final", {
      answer,
      modelUsed: usedModel || convo.modelUsed
    });

    send("done", {});
    res.end();

  } catch (err) {
    console.error("SSE endpoint error:", err);

    try {
      send("final", {
        error: `Server error: ${err.message}`
      });

      send("done", {});
    } catch { }

    res.end();
  }
});



async function waitForRun(threadId, runId) {
  while (true) {
    const run =
      await openaiClient.beta.threads.runs.retrieve(
        threadId,
        runId
      );

    if (run.status === "completed") {
      return run;
    }

    if (
      ["failed", "cancelled", "expired"]
        .includes(run.status)
    ) {
      throw new Error(
        `Run ended with status: ${run.status}`
      );
    }

    await new Promise((r) =>
      setTimeout(r, 1000)
    );
  }
}

function extractAssistantText(message) {
  if (!message?.content) return "";

  return message.content
    .map((part) =>
      part?.text?.value || part?.text || ""
    )
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

async function getLiMgContext(question) {
  const q = (question || "").toLowerCase();

  // Highest selectivity questions
  if (
    q.includes("highest li/mg selectivity") ||
    q.includes("top membranes") ||
    q.includes("highest selectivity")
  ) {
    const { rows } = await pool.query(`
      SELECT
        db_id,
        paper_title,
        membrane_normalized,
        membrane_type,
        pressure,
        flux,
        li_rejection,
        mg_rejection,
        li_mg_selectivity,
        doi
      FROM limg_data
      ORDER BY
        NULLIF(li_mg_selectivity::text, '')::numeric DESC NULLS LAST
      LIMIT 10
    `);

    return rows.map((r, i) => `Row ${i + 1}: ${JSON.stringify(r)}`).join("\n");
  }

  // Specific membrane questions
  const membraneMatch = membraneList.find(m => q.includes(m.toLowerCase()));
  if (membraneMatch) {
    const { rows } = await pool.query(
      `
      SELECT
        db_id,
        paper_title,
        membrane_normalized,
        membrane_type,
        pressure,
        flux,
        li_rejection,
        mg_rejection,
        li_mg_selectivity,
        doi
      FROM limg_data
      WHERE lower(membrane_normalized) = lower($1)
      `,
      [membraneMatch]
    );

    return rows.map((r, i) => `Row ${i + 1}: ${JSON.stringify(r)}`).join("\n");
  }

  // Fallback
  const { rows } = await pool.query(`
    SELECT
      db_id,
      paper_title,
      membrane_normalized,
      membrane_type,
      pressure,
      flux,
      li_rejection,
      mg_rejection,
      li_mg_selectivity,
      doi
    FROM limg_data
    ORDER BY
      NULLIF(li_mg_selectivity::text, '')::numeric DESC NULLS LAST
    LIMIT 25
  `);

  return rows.map((r, i) => `Row ${i + 1}: ${JSON.stringify(r)}`).join("\n");
}

const handleExperimentalSSE = async (req, res) => {
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

  const { convoId, q } = req.query || {};

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

    const convo = openaiConvos.get(convoId);
    const dbText = await getLiMgContext(question);
    const input = buildInputTextExperiment(dbText, convo.userQuestions.slice(-8), question);

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

    send("status", { message: "Creating thread…" });
    const thread = await withTimeout(openaiClient.beta.threads.create({}), 240000);

    if (!thread?.id) {
      clearInterval(ticker);
      send("final", { error: "Thread created but no thread.id returned." });
      send("done", {});
      return res.end();
    }

    send("status", { message: "Adding prompt chunks…" });
    const promptChunks = splitIntoChunks(input, 200000);
    for (const chunk of promptChunks) {
      await withTimeout(
        openaiClient.beta.threads.messages.create(thread.id, {
          role: "user",
          content: chunk
        }),
        240000
      );
    }

    send("status", { message: "Running assistant…" });
    const run = await withTimeout(
      openaiClient.beta.threads.runs.create(thread.id, {
        assistant_id: ASSISTANT_ID,
        max_prompt_tokens: 100000,
        max_completion_tokens: 10000
      }),
      240000
    );

    if (!run?.id) {
      clearInterval(ticker);
      send("final", { error: "Run created but no run.id returned." });
      send("done", {});
      return res.end();
    }

    send("status", { message: "Waiting for assistant…" });

    while (true) {
      const polled = await withTimeout(
        openaiClient.beta.threads.runs.retrieve(thread.id, run.id),
        240000
      );

      if (polled.status === "completed") break;

      if (["failed", "cancelled", "expired"].includes(polled.status)) {
        clearInterval(ticker);
        send("final", {
          error: `Run ended with status: ${polled.status}. Last error: ${JSON.stringify(polled.last_error)}`
        });
        send("done", {});
        return res.end();
      }

      await new Promise((r) => setTimeout(r, 1500));
    }

    const messages = await withTimeout(
      openaiClient.beta.threads.messages.list(thread.id),
      240000
    );

    const assistantMsg = messages.data.find((m) => m.role === "assistant");
    if (!assistantMsg) {
      clearInterval(ticker);
      send("final", { error: "Run completed but no assistant message found." });
      send("done", {});
      return res.end();
    }

    const answerText = extractAssistantText(assistantMsg) || "No response generated.";

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
    } catch { }
    return res.end();
  }
};

app.get("/api/openai-chat/ask-sse-expt", handleExperimentalSSE);
app.get("/api/limg-chat/ask-sse-expt", handleExperimentalSSE);

// Serve static files
app.use(
  express.static(path.join(__dirname, "public"))
);

// Start server
const server = app.listen(port, () => {
  console.log(`Server running on port ${port}`);
});

// Disable default timeout
server.timeout = 0;
