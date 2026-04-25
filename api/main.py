import os
import secrets
import tempfile
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Depends, UploadFile, File, Form
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from database import get_conn, init_db
from access_tokens import (
    get_object_store_manager,
    get_db_manager,
    generate_duckdb_script,
)

API_KEY = os.getenv("API_KEY", "change-me")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with get_conn() as con:
        if con.execute("SELECT COUNT(*) FROM lake.kunder").fetchone()[0] == 0:
            con.executemany("INSERT INTO lake.kunder VALUES (?, ?, ?, ?)", [
                (1, "Anna Svensson",   "anna@example.com",  "070-1234567"),
                (2, "Erik Johansson",  "erik@example.com",  "073-9876543"),
                (3, "Maria Lindqvist", "maria@example.com", "076-5551234"),
            ])
            con.executemany("INSERT INTO lake.produkter VALUES (?, ?, ?, ?)", [
                (1, "Laptop",      9999.0, 15),
                (2, "Hörlurar",     799.0, 50),
                (3, "Tangentbord", 1299.0, 30),
            ])
            con.executemany("INSERT INTO lake.ordrar (id, kund_id, produkt_id, antal) VALUES (?, ?, ?, ?)", [
                (1, 1, 1, 1), (2, 1, 2, 2), (3, 2, 3, 1),
            ])
    yield


app = FastAPI(title="DuckLake Cloud API", lifespan=lifespan)

# Servera frontend-filer
_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


# ── AUTH ──────────────────────────────────────────────────────────────────────

def verify_key(x_api_key: str = Header(...)):
    if not secrets.compare_digest(x_api_key.encode(), API_KEY.encode()):
        raise HTTPException(status_code=401, detail="Ogiltig API-nyckel")


def _is_valid_key(key: Optional[str]) -> bool:
    if not key:
        return False
    return secrets.compare_digest(key.encode(), API_KEY.encode())


# ── FRONTEND ──────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(os.path.join(_static_dir, "index.html"))


# ── MODELS ────────────────────────────────────────────────────────────────────

class NyKund(BaseModel):
    namn: str
    email: str
    telefon: Optional[str] = None

class NyProdukt(BaseModel):
    namn: str
    pris: float
    lagersaldo: Optional[int] = 0

class NyOrder(BaseModel):
    kund_id: int
    produkt_id: int
    antal: int

class CreateKeyRequest(BaseModel):
    username: str
    permission: str  # "readonly" | "readwrite"


# ── KUNDER ────────────────────────────────────────────────────────────────────

@app.get("/api/kunder")
def get_kunder():
    with get_conn() as con:
        rows = con.execute("SELECT id, namn, email, telefon FROM lake.kunder ORDER BY id").fetchall()
    return [{"id": r[0], "namn": r[1], "email": r[2], "telefon": r[3]} for r in rows]


@app.post("/api/kunder", status_code=201, dependencies=[Depends(verify_key)])
def ny_kund(kund: NyKund):
    with get_conn() as con:
        nid = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM lake.kunder").fetchone()[0]
        con.execute("INSERT INTO lake.kunder VALUES (?, ?, ?, ?)", [nid, kund.namn, kund.email, kund.telefon])
    return {"id": nid, "namn": kund.namn, "email": kund.email}


@app.delete("/api/kunder/{kund_id}", dependencies=[Depends(verify_key)])
def radera_kund(kund_id: int):
    with get_conn() as con:
        con.execute("DELETE FROM lake.kunder WHERE id = ?", [kund_id])
    return {"deleted": kund_id}


# ── PRODUKTER ─────────────────────────────────────────────────────────────────

@app.get("/api/produkter")
def get_produkter():
    with get_conn() as con:
        rows = con.execute("SELECT id, namn, pris, lagersaldo FROM lake.produkter ORDER BY id").fetchall()
    return [{"id": r[0], "namn": r[1], "pris": r[2], "lagersaldo": r[3]} for r in rows]


@app.post("/api/produkter", status_code=201, dependencies=[Depends(verify_key)])
def ny_produkt(produkt: NyProdukt):
    with get_conn() as con:
        nid = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM lake.produkter").fetchone()[0]
        con.execute("INSERT INTO lake.produkter VALUES (?, ?, ?, ?)", [nid, produkt.namn, produkt.pris, produkt.lagersaldo])
    return {"id": nid, "namn": produkt.namn, "pris": produkt.pris}


@app.delete("/api/produkter/{produkt_id}", dependencies=[Depends(verify_key)])
def radera_produkt(produkt_id: int):
    with get_conn() as con:
        con.execute("DELETE FROM lake.produkter WHERE id = ?", [produkt_id])
    return {"deleted": produkt_id}


# ── ORDRAR ────────────────────────────────────────────────────────────────────

@app.get("/api/ordrar")
def get_ordrar():
    with get_conn() as con:
        rows = con.execute("""
            SELECT o.id, k.namn, p.namn, o.antal, o.skapad
            FROM lake.ordrar o
            JOIN lake.kunder k    ON k.id = o.kund_id
            JOIN lake.produkter p ON p.id = o.produkt_id
            ORDER BY o.id
        """).fetchall()
    return [{"id": r[0], "kund": r[1], "produkt": r[2], "antal": r[3], "skapad": str(r[4])} for r in rows]


@app.post("/api/ordrar", status_code=201, dependencies=[Depends(verify_key)])
def ny_order(order: NyOrder):
    with get_conn() as con:
        nid = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM lake.ordrar").fetchone()[0]
        con.execute("INSERT INTO lake.ordrar (id, kund_id, produkt_id, antal) VALUES (?, ?, ?, ?)",
                    [nid, order.kund_id, order.produkt_id, order.antal])
    return {"id": nid, "kund_id": order.kund_id, "produkt_id": order.produkt_id, "antal": order.antal}


# ── DATASETS ──────────────────────────────────────────────────────────────────

@app.get("/api/datasets")
def lista_datasets():
    with get_conn() as con:
        tabeller = con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'lake'"
        ).fetchall()
    return [{"namn": r[0]} for r in tabeller]


@app.get("/api/datasets/{namn}")
def hamta_dataset(namn: str, limit: int = 100):
    with get_conn() as con:
        tabeller = [r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'lake'"
        ).fetchall()]
        if namn not in tabeller:
            raise HTTPException(status_code=404, detail=f"Dataset '{namn}' hittades inte")
        rows = con.execute(f"SELECT * FROM lake.{namn} LIMIT {limit}").fetchall()
        kolumner = [desc[0] for desc in con.description]
    return {"namn": namn, "kolumner": kolumner, "data": [dict(zip(kolumner, r)) for r in rows]}


@app.post("/api/datasets/upload", status_code=201, dependencies=[Depends(verify_key)])
async def ladda_upp(fil: UploadFile = File(...), tabellnamn: str = Form(...)):
    if not tabellnamn.isidentifier():
        raise HTTPException(status_code=400, detail="Ogiltigt tabellnamn")
    suffix = ".csv" if fil.filename.endswith(".csv") else ".parquet"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await fil.read())
        tmp_path = tmp.name
    try:
        with get_conn() as con:
            if suffix == ".csv":
                con.execute(f"CREATE TABLE lake.{tabellnamn} AS SELECT * FROM read_csv_auto(?)", [tmp_path])
            else:
                con.execute(f"CREATE TABLE lake.{tabellnamn} AS SELECT * FROM read_parquet(?)", [tmp_path])
    finally:
        os.unlink(tmp_path)
    return {"namn": tabellnamn, "status": "skapad"}


@app.delete("/api/datasets/{namn}", dependencies=[Depends(verify_key)])
def radera_dataset(namn: str):
    with get_conn() as con:
        tabeller = [r[0] for r in con.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'lake'"
        ).fetchall()]
        if namn not in tabeller:
            raise HTTPException(status_code=404, detail=f"Dataset '{namn}' hittades inte")
        con.execute(f"DROP TABLE lake.{namn}")
    return {"deleted": namn}


# ── ACCESS KEYS ───────────────────────────────────────────────────────────────

@app.post("/api/access-keys", status_code=201)
def skapa_nyckel(req: CreateKeyRequest, x_api_key: Optional[str] = Header(None)):
    if req.permission not in ("readonly", "readwrite"):
        raise HTTPException(status_code=400, detail="permission måste vara 'readonly' eller 'readwrite'")
    if req.permission == "readwrite" and not _is_valid_key(x_api_key):
        raise HTTPException(status_code=403, detail="Read/Write-nycklar kräver admin-behörighet (X-Api-Key)")
    if not req.username or not req.username.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="Ogiltigt användarnamn (använd bara a-z, 0-9, - och _)")

    s3_mgr = get_object_store_manager()
    db_mgr = get_db_manager()

    s3_key = None
    db_creds = None

    try:
        if s3_mgr:
            s3_key = s3_mgr.create_key(req.username, req.permission)
        db_creds = db_mgr.create_user(req.username, req.permission)
    except Exception as e:
        # Rensa upp om något gick fel halvvägs
        try:
            if s3_key and s3_mgr:
                s3_mgr.revoke_key(req.username)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Kunde inte skapa nycklar: {e}")

    script = None
    if s3_key and db_creds:
        script = generate_duckdb_script(s3_key, db_creds)
    elif db_creds:
        # Lokalt läge utan S3
        script = f"""\
-- Lokalt läge — ingen S3-konfigurerad
-- Anslut direkt via DuckDB JDBC eller psycopg2:
-- Host: {db_creds.host}:{db_creds.port}
-- Databas: {db_creds.database}
-- Användare: {db_creds.username}
-- Lösenord: {db_creds.password}
-- Behörighet: {db_creds.permission}
"""

    return {
        "username": req.username,
        "permission": req.permission,
        "duckdb_script": script,
        "s3_endpoint": s3_key.endpoint if s3_key else None,
        "s3_bucket": s3_key.bucket if s3_key else None,
        "db_host": db_creds.host if db_creds else None,
        "db_port": db_creds.port if db_creds else None,
    }


@app.get("/api/access-keys", dependencies=[Depends(verify_key)])
def lista_nycklar():
    s3_mgr = get_object_store_manager()
    if not s3_mgr:
        return {"keys": [], "info": "Ingen object store konfigurerad (lokalt läge)"}
    return {"keys": s3_mgr.list_keys()}


@app.delete("/api/access-keys/{key_id}", dependencies=[Depends(verify_key)])
def aterkalla_nyckel(key_id: str):
    s3_mgr = get_object_store_manager()
    db_mgr = get_db_manager()
    errors = []
    if s3_mgr:
        try:
            s3_mgr.revoke_key(key_id)
        except Exception as e:
            errors.append(f"S3: {e}")
    try:
        db_mgr.revoke_user(key_id)
    except Exception as e:
        errors.append(f"DB: {e}")
    if errors:
        raise HTTPException(status_code=500, detail="; ".join(errors))
    return {"revoked": key_id}


# ── HEALTH ────────────────────────────────────────────────────────────────────

@app.get("/healthz")
def health():
    return {"status": "ok"}
