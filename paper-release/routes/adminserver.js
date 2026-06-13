// routes/adminserver.js
const express = require('express');
const { Pool } = require('pg');

// 👇 You can copy your existing Pool config from server.js here:
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
  ssl: { rejectUnauthorized: false }
});

const router = express.Router();

// — Read all (GET /data)
router.get('/', async (req, res) => {
  try {
    const { rows } = await pool.query('SELECT * FROM research_data ORDER BY id');
    res.json(rows);
  } catch (err) {
    console.error('Fetch failed:', err);
    res.status(500).json({ error: 'Could not fetch data' });
  }
});

// — Create (POST /data)
router.post('/', async (req, res) => {
  const {
    id, membrane, mwco_da, pfas, removal_rate,
    isoelectric_point, water_contact_angle, mw, smiles,
    compound_size, log_kow, pka, initial_concentration,
    is_mm, pressure, ph, doi
  } = req.body;

  // Build column names and values
  const cols = [
    'membrane','mwco_da','pfas','removal_rate',
    'isoelectric_point','water_contact_angle','mw','smiles',
    'compound_size','log_kow','pka','initial_concentration',
    'is_mm','pressure','ph','doi'
  ];
  const vals = [
    membrane, mwco_da, pfas, removal_rate,
    isoelectric_point, water_contact_angle, mw, smiles,
    compound_size, log_kow, pka, initial_concentration,
    is_mm, pressure, ph, doi
  ];

  try {
    if (id) {
      // explicit ID
      const allCols      = ['id', ...cols];
      const placeholders = allCols.map((_, i) => `$${i+1}`).join(',');
      await pool.query(
        `INSERT INTO research_data (${allCols.join(',')})
         VALUES (${placeholders})`,
        [id, ...vals]
      );
    } else {
      // auto ID
      const placeholders = cols.map((_, i) => `$${i+1}`).join(',');
      await pool.query(
        `INSERT INTO research_data (${cols.join(',')})
         VALUES (${placeholders})`,
        vals
      );
    }
    // keep sequence in sync
    await pool.query(
      `SELECT setval('research_data_id_seq', (SELECT MAX(id) FROM research_data))`
    );
    res.status(201).json({ success: true });
  } catch (err) {
    console.error('Insert failed:', err);
    res.status(500).json({ error: 'Insert failed' });
  }
});

// — Delete (DELETE /data/:id)
router.delete('/:id', async (req, res) => {
  try {
    await pool.query('DELETE FROM research_data WHERE id = $1', [req.params.id]);
    // reseed sequence if you fill gaps
    await pool.query(
      `SELECT setval('research_data_id_seq', (SELECT MAX(id) FROM research_data))`
    );
    res.sendStatus(204);
  } catch (err) {
    console.error('Delete failed:', err);
    res.status(500).json({ error: 'Delete failed' });
  }
});

module.exports = router;
