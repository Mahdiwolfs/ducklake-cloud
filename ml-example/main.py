import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
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
    passenger_class: int   # 1, 2 eller 3
    is_male: int           # 1 = man, 0 = kvinna
    age: float
    family_size: int       # SibSp + Parch
    fare: float
    embarked_enc: int      # 0=S, 1=C, 2=Q


@app.post("/predict")
def predict(p: Passagerare):
    import pandas as pd
    row = pd.DataFrame([p.model_dump()])[_feature_cols]
    survival     = int(_model.predict(row)[0])
    probability  = round(float(_model.predict_proba(row)[0][1]), 4)
    return {
        "predicted_survival":   survival,
        "survival_probability": probability,
        "tolkning": "Överlevde" if survival == 1 else "Överlevde inte"
    }
