import os
import threading
from contextlib import asynccontextmanager, contextmanager
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
import duckdb
from pipeline import build

DATA_PATH = os.getenv("DATA_PATH", "./lake-data/")
CATALOG   = os.getenv("CATALOG_PATH", "./titanic.duckdb")

_con         = None
_lock        = threading.Lock()
_model       = None
_feature_cols = None
_accuracy    = None
_report      = None


@contextmanager
def get_con():
    with _lock:
        yield _con


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _con, _model, _feature_cols, _accuracy, _report
    _con = duckdb.connect()
    _con.execute("INSTALL ducklake; LOAD ducklake")
    _con.execute("INSTALL httpfs;   LOAD httpfs")
    os.makedirs(DATA_PATH, exist_ok=True)
    _con.execute(f"ATTACH 'ducklake:{CATALOG}' AS lake (DATA_PATH '{DATA_PATH}')")
    _model, _feature_cols, _accuracy, _report = build(_con)
    yield
    _con.close()


app = FastAPI(title="Titanic ML -- DuckLake Feature Store", lifespan=lifespan)


# -- Endpoints -----------------------------------------------------------------

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
        "tolkning": "Sobrevivio" if survival == 1 else "No sobrevivio"
    }


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Titanic ML Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: Arial, sans-serif; background: #f0f2f5; color: #333; }
    header { background: #1a1a2e; color: white; padding: 20px 32px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; }
    header h1 { font-size: 22px; }
    header p  { font-size: 13px; color: #aaa; margin-top: 4px; }
    .lang-switcher { display: flex; gap: 8px; align-items: center; }
    .lang-switcher span { font-size: 12px; color: #aaa; margin-right: 4px; }
    .lang-btn {
      background: rgba(255,255,255,0.08);
      border: 2px solid rgba(255,255,255,0.25);
      color: white;
      padding: 7px 16px;
      border-radius: 6px;
      cursor: pointer;
      font-size: 13px;
      font-weight: bold;
      letter-spacing: 0.5px;
      transition: background 0.15s, border-color 0.15s;
    }
    .lang-btn:hover { background: rgba(255,255,255,0.18); border-color: rgba(255,255,255,0.6); }
    .lang-btn.active { background: #0d6efd; border-color: #0d6efd; }
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
  <div>
    <h1>Titanic ML &mdash; DuckLake Feature Store</h1>
    <p data-i18n="subtitle"></p>
  </div>
  <div class="lang-switcher">
    <span data-i18n="lang_label">Idioma:</span>
    <button class="lang-btn active" id="btn-es" onclick="setLang('es')">ES</button>
    <button class="lang-btn" id="btn-sv" onclick="setLang('sv')">SV</button>
    <button class="lang-btn" id="btn-en" onclick="setLang('en')">EN</button>
  </div>
</header>

<div class="grid">
  <div class="card"><div class="label" data-i18n="lbl_accuracy"></div><div class="value green" id="acc">--</div></div>
  <div class="card"><div class="label" data-i18n="lbl_precision"></div><div class="value blue" id="prec">--</div></div>
  <div class="card"><div class="label" data-i18n="lbl_recall"></div><div class="value orange" id="rec">--</div></div>
</div>

<div class="section" style="display:flex; gap:24px; flex-wrap:wrap;">
  <div>
    <h2 data-i18n="chart_survival"></h2>
    <div class="chart-wrap"><canvas id="survivalChart" width="360" height="260"></canvas></div>
  </div>
  <div>
    <h2 data-i18n="chart_prob"></h2>
    <div class="chart-wrap"><canvas id="probChart" width="360" height="260"></canvas></div>
  </div>
</div>

<div class="section">
  <h2 data-i18n="tbl_heading"></h2>
  <table id="pred-table">
    <thead><tr>
      <th>PassengerId</th>
      <th data-i18n="tbl_prediction"></th>
      <th data-i18n="tbl_probability"></th>
    </tr></thead>
    <tbody></tbody>
  </table>
</div>

<div class="section">
  <h2 data-i18n="form_heading"></h2>
  <div class="card">
    <div class="form-grid">
      <div class="form-group">
        <label data-i18n="f_class"></label>
        <select id="f-class">
          <option value="1" data-i18n="class_1"></option>
          <option value="2" data-i18n="class_2"></option>
          <option value="3" data-i18n="class_3" selected></option>
        </select>
      </div>
      <div class="form-group">
        <label data-i18n="f_sex"></label>
        <select id="f-sex">
          <option value="1" data-i18n="sex_male"></option>
          <option value="0" data-i18n="sex_female"></option>
        </select>
      </div>
      <div class="form-group">
        <label data-i18n="f_age"></label>
        <input type="number" id="f-age" value="30" min="0" max="100">
      </div>
      <div class="form-group">
        <label data-i18n="f_family"></label>
        <input type="number" id="f-family" value="0" min="0" max="10">
      </div>
      <div class="form-group">
        <label data-i18n="f_fare"></label>
        <input type="number" id="f-fare" value="15" min="0">
      </div>
      <div class="form-group">
        <label data-i18n="f_embarked"></label>
        <select id="f-emb">
          <option value="0">Southampton</option>
          <option value="1">Cherbourg</option>
          <option value="2">Queenstown</option>
        </select>
      </div>
    </div>
    <button class="btn" id="predict-btn" onclick="predict()"></button>
    <div id="result-box"></div>
  </div>
</div>

<script>
const T = {
  es: {
    subtitle:       "Modelo Random Forest entrenado con datos de pasajeros del Titanic",
    lang_label:     "Idioma:",
    lbl_accuracy:   "Exactitud",
    lbl_precision:  "Precisi\u00f3n (sobrevivi\u00f3)",
    lbl_recall:     "Recall (sobrevivi\u00f3)",
    chart_survival: "Supervivencia en datos de entrenamiento",
    chart_prob:     "Distribuci\u00f3n de probabilidad",
    tbl_heading:    "Predicciones (\u00faltimas 20)",
    tbl_prediction: "Predicci\u00f3n",
    tbl_probability:"Probabilidad",
    form_heading:   "Probar un pasajero",
    f_class:        "Clase",
    class_1:        "1 \u2014 Primera",
    class_2:        "2 \u2014 Segunda",
    class_3:        "3 \u2014 Tercera",
    f_sex:          "Sexo",
    sex_male:       "Hombre",
    sex_female:     "Mujer",
    f_age:          "Edad",
    f_family:       "Tama\u00f1o familiar (SibSp+Parch)",
    f_fare:         "Precio del billete (\u00a3)",
    f_embarked:     "Puerto de embarque",
    btn_predict:    "Predecir",
    survived:       "Sobrevivi\u00f3",
    died:           "No sobrevivi\u00f3",
    chart_survived: "Sobrevivi\u00f3",
    chart_died:     "No sobrevivi\u00f3",
  },
  sv: {
    subtitle:       "Random Forest-modell tr\u00e4nad p\u00e5 Titanic-passagerardata",
    lang_label:     "Spr\u00e5k:",
    lbl_accuracy:   "Tr\u00e4ffs\u00e4kerhet",
    lbl_precision:  "Precision (\u00f6verlevde)",
    lbl_recall:     "Recall (\u00f6verlevde)",
    chart_survival: "\u00d6verlevnad i tr\u00e4ningsdata",
    chart_prob:     "Sannolikhetsf\u00f6rdelning",
    tbl_heading:    "Prediktioner (senaste 20)",
    tbl_prediction: "F\u00f6ruts\u00e4gelse",
    tbl_probability:"Sannolikhet",
    form_heading:   "Testa en passagerare",
    f_class:        "Klass",
    class_1:        "1 \u2014 F\u00f6rsta",
    class_2:        "2 \u2014 Andra",
    class_3:        "3 \u2014 Tredje",
    f_sex:          "K\u00f6n",
    sex_male:       "Man",
    sex_female:     "Kvinna",
    f_age:          "\u00c5lder",
    f_family:       "Familjestorlek (SibSp+Parch)",
    f_fare:         "Biljettpris (\u00a3)",
    f_embarked:     "Ombordstigning",
    btn_predict:    "F\u00f6ruts\u00e4g",
    survived:       "\u00d6verlevde",
    died:           "\u00d6verlevde inte",
    chart_survived: "\u00d6verlevde",
    chart_died:     "\u00d6verlevde inte",
  },
  en: {
    subtitle:       "Random Forest model trained on Titanic passenger data",
    lang_label:     "Language:",
    lbl_accuracy:   "Accuracy",
    lbl_precision:  "Precision (survived)",
    lbl_recall:     "Recall (survived)",
    chart_survival: "Survival in training data",
    chart_prob:     "Probability distribution",
    tbl_heading:    "Predictions (latest 20)",
    tbl_prediction: "Prediction",
    tbl_probability:"Probability",
    form_heading:   "Test a passenger",
    f_class:        "Class",
    class_1:        "1 \u2014 First",
    class_2:        "2 \u2014 Second",
    class_3:        "3 \u2014 Third",
    f_sex:          "Sex",
    sex_male:       "Male",
    sex_female:     "Female",
    f_age:          "Age",
    f_family:       "Family size (SibSp+Parch)",
    f_fare:         "Ticket fare (\u00a3)",
    f_embarked:     "Port of embarkation",
    btn_predict:    "Predict",
    survived:       "Survived",
    died:           "Did not survive",
    chart_survived: "Survived",
    chart_died:     "Did not survive",
  }
};

let lang = 'es';
let survivalChart;

function t(key) { return T[lang][key] || key; }

function setLang(l) {
  lang = l;
  document.documentElement.lang = l;
  ['es','sv','en'].forEach(code => {
    document.getElementById('btn-' + code).classList.toggle('active', code === l);
  });
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.getElementById('predict-btn').textContent = t('btn_predict');
  if (survivalChart) {
    survivalChart.data.labels = [t('chart_died'), t('chart_survived')];
    survivalChart.update();
  }
  document.querySelectorAll('.badge.yes').forEach(b => b.textContent = t('survived'));
  document.querySelectorAll('.badge.no').forEach(b  => b.textContent = t('died'));
}

async function load() {
  const [acc, preds, feats] = await Promise.all([
    fetch('/accuracy').then(r => r.json()),
    fetch('/predictions?limit=20').then(r => r.json()),
    fetch('/features?limit=891').then(r => r.json()),
  ]);

  document.getElementById('acc').textContent  = (acc.accuracy * 100).toFixed(1) + '%';
  document.getElementById('prec').textContent = (acc.report['1'].precision * 100).toFixed(1) + '%';
  document.getElementById('rec').textContent  = (acc.report['1'].recall * 100).toFixed(1) + '%';

  const tbody = document.querySelector('#pred-table tbody');
  preds.forEach(p => {
    const tr = document.createElement('tr');
    const badge = p.predicted_survival === 1
      ? '<span class="badge yes">' + t('survived') + '</span>'
      : '<span class="badge no">'  + t('died')     + '</span>';
    tr.innerHTML = '<td>' + p.PassengerId + '</td><td>' + badge + '</td><td>' + (p.survival_probability * 100).toFixed(1) + '%</td>';
    tbody.appendChild(tr);
  });

  const survived = feats.filter(f => f.label === 1).length;
  const died     = feats.length - survived;
  survivalChart = new Chart(document.getElementById('survivalChart'), {
    type: 'bar',
    data: {
      labels: [t('chart_died'), t('chart_survived')],
      datasets: [{ data: [died, survived], backgroundColor: ['#f8d7da', '#d4edda'], borderColor: ['#dc3545', '#28a745'], borderWidth: 2 }]
    },
    options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true } } }
  });

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

  setLang('es');
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
  const survived = data.predicted_survival === 1;
  box.className  = survived ? 'survived' : 'died';
  box.innerHTML  = '<strong>' + (survived ? t('survived') : t('died')) + '</strong> &mdash; ' + t('tbl_probability') + ': ' + (data.survival_probability * 100).toFixed(1) + '%';
}

load();
</script>
</body>
</html>"""
