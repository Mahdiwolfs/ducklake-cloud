import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import duckdb
from pipeline import build

DATA_PATH = os.getenv("DATA_PATH", "./lake-data/")
CATALOG   = os.getenv("CATALOG_PATH", "./titanic.duckdb")

_model       = None
_feature_cols = None
_accuracy    = None
_report      = None


def get_con():
    con = duckdb.connect()
    con.execute("INSTALL ducklake; LOAD ducklake")
    con.execute("INSTALL httpfs;   LOAD httpfs")
    os.makedirs(DATA_PATH, exist_ok=True)
    con.execute(f"ATTACH 'ducklake:{CATALOG}' AS lake (DATA_PATH '{DATA_PATH}')")
    return con


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _model, _feature_cols, _accuracy, _report
    with get_con() as con:
        _model, _feature_cols, _accuracy, _report = build(con)
    yield


app = FastAPI(title="Titanic ML — DuckLake Feature Store", lifespan=lifespan)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.get("/accuracy")
def accuracy():
    return {
        "accuracy": round(_accuracy, 4),
        "report":   _report
    }


@app.get("/features")
def features(limit: int = 10):
    with get_con() as con:
        rows = con.execute(f"SELECT * FROM lake.features LIMIT {limit}").fetchall()
        cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


@app.get("/predictions")
def predictions(limit: int = 10):
    with get_con() as con:
        rows = con.execute(
            f"SELECT * FROM lake.predictions ORDER BY PassengerId LIMIT {limit}"
        ).fetchall()
        cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


@app.get("/snapshots")
def snapshots():
    with get_con() as con:
        rows = con.execute("SELECT * FROM ducklake_snapshots('lake') ORDER BY snapshot_id DESC").fetchall()
        cols = [d[0] for d in con.description]
    return [dict(zip(cols, r)) for r in rows]


class Passagerare(BaseModel):
    passenger_class: int
    is_male: int
    age: float
    family_size: int
    fare: float
    embarked_enc: int


@app.post("/predict")
def predict(p: Passagerare):
    import pandas as pd
    row = pd.DataFrame([p.model_dump()])[_feature_cols]
    survival    = int(_model.predict(row)[0])
    probability = round(float(_model.predict_proba(row)[0][1]), 4)
    return {
        "predicted_survival":   survival,
        "survival_probability": probability,
        "tolkning": "Överlevde" if survival == 1 else "Överlevde inte"
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Titanic ML Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; background: #f0f2f5; color: #333; }
    header { background: #1a1a2e; color: white; padding: 20px 32px; }
    header h1 { font-size: 22px; }
    header p  { font-size: 13px; color: #aaa; margin-top: 4px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; padding: 24px 32px 0; }
    .card { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
    .card .label { font-size: 12px; color: #888; text-transform: uppercase; letter-spacing: .5px; }
    .card .value { font-size: 36px; font-weight: bold; margin-top: 6px; }
    .card .value.green { color: #28a745; }
    .card .value.blue  { color: #0d6efd; }
    .card .value.orange{ color: #fd7e14; }
    .section { margin: 24px 32px; }
    .section h2 { font-size: 16px; font-weight: bold; margin-bottom: 12px; }
    .chart-wrap { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 1px 4px rgba(0,0,0,.08); max-width: 420px; }
    table { width: 100%; border-collapse: collapse; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); font-size: 13px; }
    th { background: #1a1a2e; color: white; padding: 10px 14px; text-align: left; font-size: 12px; }
    td { padding: 9px 14px; border-bottom: 1px solid #f0f0f0; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #f8f9ff; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 20px; font-size: 11px; font-weight: bold; }
    .badge.yes { background: #d4edda; color: #155724; }
    .badge.no  { background: #f8d7da; color: #721c24; }
    .form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; }
    .form-group label { font-size: 12px; color: #555; display: block; margin-bottom: 4px; }
    .form-group select, .form-group input { width: 100%; padding: 8px 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 13px; }
    .btn { margin-top: 16px; padding: 10px 24px; background: #1a1a2e; color: white; border: none; border-radius: 6px; font-size: 14px; cursor: pointer; }
    .btn:hover { background: #0d6efd; }
    #result-box { margin-top: 16px; padding: 16px; border-radius: 8px; display: none; font-size: 14px; }
    #result-box.survived { background: #d4edda; color: #155724; border: 1px solid #c3e6cb; }
    #result-box.died     { background: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }
  </style>
</head>
<body>
<header>
  <h1>Titanic ML — DuckLake Feature Store</h1>
  <p>Random Forest-modell tränad på Titanic-passagerardata</p>
</header>

<div class="grid" id="stat-cards">
  <div class="card"><div class="label">Träffsäkerhet</div><div class="value green" id="acc">—</div></div>
  <div class="card"><div class="label">Precision (överlevde)</div><div class="value blue" id="prec">—</div></div>
  <div class="card"><div class="label">Recall (överlevde)</div><div class="value orange" id="rec">—</div></div>
</div>

<div class="section" style="display:flex; gap:24px; flex-wrap:wrap;">
  <div>
    <h2>Överlevnad i träningsdata</h2>
    <div class="chart-wrap"><canvas id="survivalChart" width="360" height="260"></canvas></div>
  </div>
  <div>
    <h2>Sannolikhetsfördelning</h2>
    <div class="chart-wrap"><canvas id="probChart" width="360" height="260"></canvas></div>
  </div>
</div>

<div class="section">
  <h2>Prediktioner (senaste 20)</h2>
  <table id="pred-table">
    <thead><tr><th>PassengerId</th><th>Förutsägelse</th><th>Sannolikhet</th></tr></thead>
    <tbody></tbody>
  </table>
</div>

<div class="section">
  <h2>Testa en passagerare</h2>
  <div class="card">
    <div class="form-grid">
      <div class="form-group">
        <label>Klass</label>
        <select id="f-class"><option value="1">1 — Första</option><option value="2">2 — Andra</option><option value="3" selected>3 — Tredje</option></select>
      </div>
      <div class="form-group">
        <label>Kön</label>
        <select id="f-sex"><option value="1">Man</option><option value="0">Kvinna</option></select>
      </div>
      <div class="form-group">
        <label>Ålder</label>
        <input type="number" id="f-age" value="30" min="0" max="100">
      </div>
      <div class="form-group">
        <label>Familjestorlek (SibSp+Parch)</label>
        <input type="number" id="f-family" value="0" min="0" max="10">
      </div>
      <div class="form-group">
        <label>Biljettpris (£)</label>
        <input type="number" id="f-fare" value="15" min="0">
      </div>
      <div class="form-group">
        <label>Ombordstigning</label>
        <select id="f-emb"><option value="0">Southampton</option><option value="1">Cherbourg</option><option value="2">Queenstown</option></select>
      </div>
    </div>
    <button class="btn" onclick="predict()">Förutsäg</button>
    <div id="result-box"></div>
  </div>
</div>

<script>
async function load() {
  const [acc, preds, feats] = await Promise.all([
    fetch('/accuracy').then(r => r.json()),
    fetch('/predictions?limit=20').then(r => r.json()),
    fetch('/features?limit=891').then(r => r.json()),
  ]);

  document.getElementById('acc').textContent  = (acc.accuracy * 100).toFixed(1) + '%';
  document.getElementById('prec').textContent = (acc.report['1'].precision * 100).toFixed(1) + '%';
  document.getElementById('rec').textContent  = (acc.report['1'].recall * 100).toFixed(1) + '%';

  // Predictions table
  const tbody = document.querySelector('#pred-table tbody');
  preds.forEach(p => {
    const tr = document.createElement('tr');
    const badge = p.predicted_survival === 1
      ? '<span class="badge yes">Överlevde</span>'
      : '<span class="badge no">Överlevde inte</span>';
    tr.innerHTML = `<td>${p.PassengerId}</td><td>${badge}</td><td>${(p.survival_probability * 100).toFixed(1)}%</td>`;
    tbody.appendChild(tr);
  });

  // Survival bar chart
  const survived = feats.filter(f => f.label === 1).length;
  const died     = feats.length - survived;
  new Chart(document.getElementById('survivalChart'), {
    type: 'bar',
    data: {
      labels: ['Överlevde inte', 'Överlevde'],
      datasets: [{ data: [died, survived], backgroundColor: ['#f8d7da', '#d4edda'], borderColor: ['#dc3545', '#28a745'], borderWidth: 2 }]
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
  });

  // Probability histogram
  const buckets = Array(10).fill(0);
  preds.forEach(p => { buckets[Math.min(9, Math.floor(p.survival_probability * 10))]++; });
  new Chart(document.getElementById('probChart'), {
    type: 'bar',
    data: {
      labels: ['0-10%','10-20%','20-30%','30-40%','40-50%','50-60%','60-70%','70-80%','80-90%','90-100%'],
      datasets: [{ data: buckets, backgroundColor: '#cfe2ff', borderColor: '#0d6efd', borderWidth: 2 }]
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
  });
}

async function predict() {
  const body = {
    passenger_class: parseInt(document.getElementById('f-class').value),
    is_male:         parseInt(document.getElementById('f-sex').value),
    age:             parseFloat(document.getElementById('f-age').value),
    family_size:     parseInt(document.getElementById('f-family').value),
    fare:            parseFloat(document.getElementById('f-fare').value),
    embarked_enc:    parseInt(document.getElementById('f-emb').value),
  };
  const res  = await fetch('/predict', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
  const data = await res.json();
  const box  = document.getElementById('result-box');
  box.style.display = 'block';
  box.className = data.predicted_survival === 1 ? 'result-box survived' : 'result-box died';
  box.innerHTML = `<strong>${data.tolkning}</strong> — Sannolikhet: ${(data.survival_probability * 100).toFixed(1)}%`;
}

load();
</script>
</body>
</html>"""
