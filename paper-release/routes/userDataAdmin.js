// routes/userDataAdmin.js

const express = require('express');
const { Pool } = require('pg');
const router  = express.Router();

// Configure your Postgres connection
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false }
});

// Helper to parse numeric fields (strings → number or null)
function parseNum(v) {
  if (v === null || v === undefined) return null;
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : null;
}

// ─── 1️⃣ List pending submissions ───────────────────────────────
router.get('/pending', async (req, res) => {
  try {
    const { rows } = await pool.query(
      'SELECT * FROM single_entries ORDER BY id'
    );
    res.json(rows);
  } catch (err) {
    console.error('Fetch pending failed:', err);
    res.status(500).json({ error: 'Could not fetch submissions' });
  }
});

// ─── 2️⃣ Approve a submission with custom/next/lowest ID ─────────
router.post('/:id/approve', async (req, res) => {
  const subId  = parseInt(req.params.id, 10);
  const target = req.query.targetId;

  try {
    // 1) Fetch the single_entries row
    const { rows } = await pool.query(
      'SELECT * FROM single_entries WHERE id = $1',
      [subId]
    );
    if (rows.length === 0) {
      return res.status(404).json({ error: 'Submission not found' });
    }
    const s = rows[0];

    // 2) Determine target ID
    let idToUse;
    if (target === 'next') {
      const mx = await pool.query('SELECT MAX(id) AS m FROM research_data');
      idToUse = (mx.rows[0].m || 0) + 1;
    } else if (target === 'lowest') {
      const idsRes = await pool.query('SELECT id FROM research_data ORDER BY id');
      const existing = idsRes.rows.map(r => r.id);
      idToUse = 1;
      while (existing.includes(idToUse)) {
        idToUse++;
      }
    } else {
      const custom = parseInt(target, 10);
      idToUse = Number.isInteger(custom) && custom > 0
        ? custom
        : (await pool.query('SELECT MAX(id) AS m FROM research_data')).rows[0].m + 1;
    }

    // 3) Parse all fields
    const membrane            = s.membrane;
    const mwco_da             = parseNum(s.mwco_da);
    const pfas                = s.pfas;
    const removal_rate        = parseNum(s.removal_rate);
    const isoelectric_point   = parseNum(s.isoelectric_point);
    const water_contact_angle = parseNum(s.water_contact_angle);
    const mw                  = parseNum(s.mw);
    const smiles              = s.smiles;
    const compound_size       = parseNum(s.compound_size);
    const log_kow             = parseNum(s.log_kow);
    const pka                 = parseNum(s.pka);
    const initial_concentration = parseNum(s.initial_concentration);
    const is_mm               = s.is_mm ? 1 : 0;  // convert boolean to 1/0
    const pressure            = parseNum(s.pressure);
    const ph                  = parseNum(s.ph);
    const doi                 = s.doi_reference;  // map to research_data.doi

    // 4) Insert into research_data (explicit ID)
    await pool.query(
      `INSERT INTO research_data
         (id, membrane, mwco_da, pfas, removal_rate,
          isoelectric_point, water_contact_angle, mw, smiles,
          compound_size, log_kow, pka, initial_concentration,
          is_mm, pressure, ph, doi)
       VALUES
         ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)`,
      [
        idToUse,
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
        doi
      ]
    );

    // 5) Delete from single_entries
    await pool.query(
      'DELETE FROM single_entries WHERE id = $1',
      [subId]
    );

    // 6) Reseed research_data sequence
    await pool.query(
      `SELECT setval('research_data_id_seq', (SELECT MAX(id) FROM research_data))`
    );

    res.sendStatus(204);
  } catch (err) {
    console.error('Approve failed:', err);
    res.status(500).json({ error: 'Approval failed' });
  }
});

// ─── 3️⃣ Reject a submission ────────────────────────────────────
router.delete('/:id', async (req, res) => {
  const subId = parseInt(req.params.id, 10);
  try {
    await pool.query(
      'DELETE FROM single_entries WHERE id = $1',
      [subId]
    );
    res.sendStatus(204);
  } catch (err) {
    console.error('Reject failed:', err);
    res.status(500).json({ error: 'Reject failed' });
  }
});

module.exports = router;
