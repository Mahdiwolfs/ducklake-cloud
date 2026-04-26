# Lokal setup — Bygg DuckLake från grunden

Den här guiden tar dig från en tom mapp till ett fullt fungerande DuckLake-system på din egen dator. Du behöver inte klona något repo — du skapar varje fil själv.

---

## Vad du bygger

```
Din dator
├── PostgreSQL  (lagrar metadata om tabeller och snapshots)
├── MinIO       (lagrar Parquet-filer med den faktiska datan)
└── Python API  (webbgränssnitt + REST API för att hantera datan)
```

När du är klar har du ett system som körs på `http://localhost:8000` där du kan:
- Se och bläddra i datasets
- Ladda upp CSV- och Parquet-filer
- Skapa access-nycklar för att ansluta med DuckDB

---

## Förutsättningar

Installera dessa innan du börjar:

| Program | Varför | Ladda ner |
|---------|--------|-----------|
| **Docker Desktop** | Kör PostgreSQL, MinIO och API:et | [docker.com/get-started](https://www.docker.com/get-started/) |
| **VS Code** (rekommenderas) | Textredigerare | [code.visualstudio.com](https://code.visualstudio.com/) |

Verifiera att Docker fungerar:
```bash
docker --version
# Docker version 27.x.x ...
```

---

## Steg 1 — Skapa projektmappen

Öppna en terminal och kör:

```bash
mkdir ducklake-projekt
cd ducklake-projekt
mkdir -p api/static
```

Din mappstruktur ska se ut så här:

```
ducklake-projekt/
├── docker-compose.yml
└── api/
    ├── Dockerfile
    ├── requirements.txt
    ├── database.py
    ├── access_tokens.py
    ├── main.py
    └── static/
        └── index.html
```

Öppna mappen i VS Code:
```bash
code .
```

---

## Steg 2 — docker-compose.yml

Skapa filen `docker-compose.yml` i projektets rot med detta innehåll:

```yaml
services:

  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB:       ducklake
      POSTGRES_USER:     duck
      POSTGRES_PASSWORD: postgres
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "duck", "-d", "ducklake"]
      interval: 5s
      retries: 10

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER:     minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio_data:/data
    ports:
      - "9002:9000"
      - "9003:9001"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 5s
      retries: 10

  api:
    build: ./api
    ports:
      - "8000:8000"
    environment:
      POSTGRES_HOST:     postgres
      POSTGRES_DB:       ducklake
      POSTGRES_USER:     duck
      POSTGRES_PASSWORD: postgres
      S3_ENDPOINT:       minio:9000
      S3_KEY_ID:         minioadmin
      S3_SECRET:         minioadmin
      S3_BUCKET:         ducklake
      API_KEY:           change-me
    depends_on:
      postgres:
        condition: service_healthy
      minio:
        condition: service_healthy

volumes:
  postgres_data:
  minio_data:
```

**Vad som händer här:**
- `postgres` — kör PostgreSQL som håller koll på vilka tabeller som finns (DuckLake-katalogen)
- `minio` — kör MinIO som lagrar Parquet-filerna (den faktiska datan)
- `api` — bygger och kör ditt Python-API
- `depends_on` — API:et startar inte förrän PostgreSQL och MinIO är redo

> **OBS:** MinIO körs på port `9002` (inte `9000`) för att undvika konflikter med andra program. MinIO-konsolen finns på port `9003`.

---

## Steg 3 — api/requirements.txt

Skapa filen `api/requirements.txt`:

```
fastapi==0.136.0
uvicorn==0.44.0
duckdb==1.3.1
minio==7.2.15
psycopg2-binary==2.9.9
python-multipart==0.0.20
requests==2.32.3
```

---

## Steg 4 — api/Dockerfile

Skapa filen `api/Dockerfile`:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python3 -c "import duckdb; con = duckdb.connect(); con.execute('INSTALL ducklake'); con.execute('INSTALL postgres'); con.execute('INSTALL httpfs')"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Vad som händer här:**
- Installerar Python-biblioteken
- Installerar DuckDB-tilläggen i förväg (annars tar det lång tid vid första anrop)
- Kopierar din kod och startar API:et

---

## Steg 5 — api/database.py

Skapa filen `api/database.py`:

```python
import duckdb
import os

POSTGRES_HOST     = os.getenv("POSTGRES_HOST",     "localhost")
POSTGRES_DB       = os.getenv("POSTGRES_DB",       "ducklake")
POSTGRES_USER     = os.getenv("POSTGRES_USER",     "duck")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_KEY_ID   = os.getenv("S3_KEY_ID",   "minioadmin")
S3_SECRET   = os.getenv("S3_SECRET",   "minioadmin")
S3_BUCKET   = os.getenv("S3_BUCKET",   "ducklake")
S3_REGION   = os.getenv("S3_REGION",   "local")


def _ensure_bucket():
    if not S3_ENDPOINT:
        return
    from minio import Minio
    client = Minio(S3_ENDPOINT, access_key=S3_KEY_ID, secret_key=S3_SECRET, secure=False)
    if not client.bucket_exists(S3_BUCKET):
        client.make_bucket(S3_BUCKET)


def get_conn() -> duckdb.DuckDBPyConnection:
    _ensure_bucket()

    con = duckdb.connect()
    con.execute("INSTALL ducklake; LOAD ducklake")
    con.execute("INSTALL postgres;  LOAD postgres")

    con.execute(f"""
        CREATE OR REPLACE SECRET (
            TYPE     postgres,
            HOST     '{POSTGRES_HOST}',
            PORT     5432,
            DATABASE '{POSTGRES_DB}',
            USER     '{POSTGRES_USER}',
            PASSWORD '{POSTGRES_PASSWORD}'
        )
    """)

    if S3_ENDPOINT:
        con.execute("INSTALL httpfs; LOAD httpfs")
        con.execute(f"""
            CREATE OR REPLACE SECRET (
                TYPE      s3,
                KEY_ID    '{S3_KEY_ID}',
                SECRET    '{S3_SECRET}',
                REGION    '{S3_REGION}',
                ENDPOINT  '{S3_ENDPOINT}',
                URL_STYLE 'path',
                USE_SSL   false
            )
        """)
        data_path = f"s3://{S3_BUCKET}/"
    else:
        data_path = os.getenv("DATA_PATH", "./data/lake/")
        os.makedirs(data_path, exist_ok=True)

    con.execute(f"""
        ATTACH 'ducklake:postgres:dbname={POSTGRES_DB}'
        AS lake (DATA_PATH '{data_path}')
    """)

    return con


def init_db():
    with get_conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS lake.kunder (
                id INTEGER, namn VARCHAR NOT NULL,
                email VARCHAR NOT NULL, telefon VARCHAR
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS lake.produkter (
                id INTEGER, namn VARCHAR NOT NULL,
                pris DOUBLE NOT NULL, lagersaldo INTEGER DEFAULT 0
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS lake.ordrar (
                id INTEGER, kund_id INTEGER, produkt_id INTEGER,
                antal INTEGER NOT NULL, skapad TIMESTAMP DEFAULT current_timestamp
            )
        """)
```

**Vad som händer här:**
- Läser konfiguration från miljövariabler
- Skapar bucket i MinIO om den inte finns
- Kopplar DuckDB till PostgreSQL (katalog) och MinIO (lagring)
- Skapar tre exempeltabeller: kunder, produkter, ordrar

---

## Steg 6 — api/access_tokens.py

Skapa filen `api/access_tokens.py`:

```python
import json
import os
import secrets
import string
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass


# ── DATA CLASSES ──────────────────────────────────────────────────────────────

@dataclass
class ObjectStoreKey:
    key_id: str
    secret: str
    permission: str  # "readonly" | "readwrite"
    endpoint: str
    bucket: str


@dataclass
class DatabaseCredentials:
    host: str
    port: int
    database: str
    username: str
    password: str
    permission: str  # "readonly" | "readwrite"


# ── INTERFACES ────────────────────────────────────────────────────────────────

class ObjectStoreAccessTokenManager(ABC):
    @abstractmethod
    def create_key(self, username: str, permission: str) -> ObjectStoreKey: ...

    @abstractmethod
    def revoke_key(self, key_id: str) -> None: ...

    @abstractmethod
    def list_keys(self) -> list[dict]: ...


class DatabaseAccessTokenManager(ABC):
    @abstractmethod
    def create_user(self, username: str, permission: str) -> DatabaseCredentials: ...

    @abstractmethod
    def revoke_user(self, username: str) -> None: ...


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _rand(n: int = 32) -> str:
    ab = string.ascii_letters + string.digits
    return "".join(secrets.choice(ab) for _ in range(n))


# ── S3 BUCKET POLICIES ────────────────────────────────────────────────────────

_POLICY_READONLY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": ["s3:GetObject", "s3:GetBucketLocation", "s3:ListBucket"],
        "Resource": ["arn:aws:s3:::*"],
    }],
})

_POLICY_READWRITE = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Action": ["s3:*"],
        "Resource": ["arn:aws:s3:::*"],
    }],
})


# ── MINIO IMPLEMENTATION ──────────────────────────────────────────────────────

class MinioAccessTokenManager(ObjectStoreAccessTokenManager):

    def __init__(self, endpoint: str, admin_key: str, admin_secret: str, bucket: str):
        from minio import MinioAdmin
        from minio.credentials import StaticProvider
        self._admin = MinioAdmin(endpoint, credentials=StaticProvider(admin_key, admin_secret), secure=False)
        self._endpoint = endpoint
        self._bucket = bucket
        for name, policy in [("ducklake-ro", _POLICY_READONLY), ("ducklake-rw", _POLICY_READWRITE)]:
            try:
                with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
                    f.write(policy)
                    tmp_path = f.name
                self._admin.policy_add(name, tmp_path)
            except Exception:
                pass

    def create_key(self, username: str, permission: str) -> ObjectStoreKey:
        secret = _rand()
        self._admin.user_add(username, secret)
        try:
            self._admin.attach_policy(["ducklake-ro" if permission == "readonly" else "ducklake-rw"], user=username)
        except Exception as e:
            if "AlreadyApplied" not in str(e):
                raise
        return ObjectStoreKey(key_id=username, secret=secret,
                              permission=permission, endpoint=self._endpoint,
                              bucket=self._bucket)

    def revoke_key(self, key_id: str) -> None:
        self._admin.user_remove(key_id)

    def list_keys(self) -> list[dict]:
        try:
            users = self._admin.user_list()
            result = []
            for ak, info in users.items():
                policy = getattr(info, "policy_name", None) or (info.get("policyName") if isinstance(info, dict) else None)
                result.append({"key_id": ak, "permission": "readwrite" if policy == "ducklake-rw" else "readonly"})
            return result
        except Exception:
            return []


# ── GARAGE IMPLEMENTATION ─────────────────────────────────────────────────────

class GarageAccessTokenManager(ObjectStoreAccessTokenManager):
    """Används i produktion — MinIO är deprecated."""

    def __init__(self, admin_url: str, admin_token: str, s3_endpoint: str, bucket: str):
        import requests
        self._s = requests.Session()
        self._s.headers["Authorization"] = f"Bearer {admin_token}"
        self._base = admin_url.rstrip("/")
        self._endpoint = s3_endpoint
        self._bucket = bucket

    def create_key(self, username: str, permission: str) -> ObjectStoreKey:
        resp = self._s.post(f"{self._base}/v2/CreateKey", json={"name": username})
        resp.raise_for_status()
        data = resp.json()
        key_id = data["accessKeyId"]
        secret = data["secretAccessKey"]
        perms = {"read": True, "write": permission == "readwrite", "owner": False}
        self._s.post(f"{self._base}/v2/BucketAllowKey",
                     json={"bucketId": self._bucket, "accessKeyId": key_id,
                           "permissions": perms}).raise_for_status()
        return ObjectStoreKey(key_id=key_id, secret=secret, permission=permission,
                              endpoint=self._endpoint, bucket=self._bucket)

    def revoke_key(self, key_id: str) -> None:
        self._s.delete(f"{self._base}/v2/DeleteKey?id={key_id}").raise_for_status()

    def list_keys(self) -> list[dict]:
        resp = self._s.get(f"{self._base}/v2/ListKeys")
        resp.raise_for_status()
        return [{"key_id": e.get("accessKeyId", ""), "permission": "unknown"} for e in resp.json()]


# ── POSTGRESQL USER MANAGER ───────────────────────────────────────────────────

class PostgresAccessTokenManager(DatabaseAccessTokenManager):

    def __init__(self, host: str, port: int, database: str, admin_user: str, admin_password: str):
        self._host = host
        self._port = port
        self._database = database
        self._admin_user = admin_user
        self._admin_password = admin_password

    def _conn(self):
        import psycopg2
        return psycopg2.connect(host=self._host, port=self._port, dbname=self._database,
                                user=self._admin_user, password=self._admin_password)

    def create_user(self, username: str, permission: str) -> DatabaseCredentials:
        pw = _rand(24)
        with self._conn() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(f'CREATE USER "{username}" WITH PASSWORD %s', (pw,))
                cur.execute(f'GRANT CONNECT ON DATABASE "{self._database}" TO "{username}"')
                cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog','information_schema')")
                schemas = [r[0] for r in cur.fetchall()]
                for schema in schemas:
                    cur.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO "{username}"')
                    if permission == "readwrite":
                        cur.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO "{username}"')
                    else:
                        cur.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{username}"')
        return DatabaseCredentials(host=self._host, port=self._port, database=self._database,
                                   username=username, password=pw, permission=permission)

    def revoke_user(self, username: str) -> None:
        with self._conn() as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT IN ('pg_catalog','information_schema')")
                schemas = [r[0] for r in cur.fetchall()]
                for schema in schemas:
                    cur.execute(f'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA "{schema}" FROM "{username}"')
                    cur.execute(f'REVOKE USAGE ON SCHEMA "{schema}" FROM "{username}"')
                cur.execute(f'REVOKE CONNECT ON DATABASE "{self._database}" FROM "{username}"')
                cur.execute(f'DROP USER IF EXISTS "{username}"')


# ── SCRIPT GENERATOR ──────────────────────────────────────────────────────────

def generate_duckdb_script(s3: ObjectStoreKey, db: DatabaseCredentials) -> str:
    return f"""\
-- ============================================================
-- DuckLake-anslutningsscript — genererat automatiskt
-- Klistra in i DuckDB CLI eller en Jupyter-cell
-- Behörighet: {s3.permission}
-- ============================================================

INSTALL ducklake;
INSTALL postgres;
INSTALL httpfs;

LOAD ducklake;
LOAD postgres;
LOAD httpfs;

-- PostgreSQL-katalog (DuckLake metadata)
CREATE OR REPLACE SECRET pg_secret (
    TYPE     postgres,
    HOST     '{db.host}',
    PORT     {db.port},
    DATABASE '{db.database}',
    USER     '{db.username}',
    PASSWORD '{db.password}'
);

-- S3-lagring (Parquet-filer)
CREATE OR REPLACE SECRET s3_secret (
    TYPE      s3,
    PROVIDER  config,
    KEY_ID    '{s3.key_id}',
    SECRET    '{s3.secret}',
    REGION    'local',
    ENDPOINT  '{s3.endpoint}',
    URL_STYLE 'path',
    USE_SSL   false
);

-- Anslut till DuckLake
ATTACH 'ducklake:postgres:dbname={db.database}' AS lake (DATA_PATH 's3://{s3.bucket}/');

-- Exempel:
-- SHOW TABLES FROM lake;
-- SELECT * FROM lake.kunder LIMIT 10;
"""


# ── FACTORY ───────────────────────────────────────────────────────────────────

def get_object_store_manager() -> ObjectStoreAccessTokenManager | None:
    garage_url = os.getenv("GARAGE_ADMIN_URL", "")
    if garage_url:
        return GarageAccessTokenManager(
            admin_url=garage_url,
            admin_token=os.getenv("GARAGE_ADMIN_TOKEN", ""),
            s3_endpoint=os.getenv("S3_ENDPOINT", ""),
            bucket=os.getenv("S3_BUCKET", "ducklake"),
        )
    s3_endpoint = os.getenv("S3_ENDPOINT", "")
    if s3_endpoint:
        return MinioAccessTokenManager(
            endpoint=s3_endpoint,
            admin_key=os.getenv("S3_KEY_ID", "minioadmin"),
            admin_secret=os.getenv("S3_SECRET", "minioadmin"),
            bucket=os.getenv("S3_BUCKET", "ducklake"),
        )
    return None


def get_db_manager() -> PostgresAccessTokenManager:
    return PostgresAccessTokenManager(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=5432,
        database=os.getenv("POSTGRES_DB", "ducklake"),
        admin_user=os.getenv("POSTGRES_USER", "duck"),
        admin_password=os.getenv("POSTGRES_PASSWORD", "postgres"),
    )
```

**Vad som händer här:**
- `MinioAccessTokenManager` — skapar/tar bort MinIO-användare med rätt behörigheter
- `PostgresAccessTokenManager` — skapar/tar bort PostgreSQL-användare
- `generate_duckdb_script()` — genererar ett färdigt script studenter kan kopiera och köra
- `get_object_store_manager()` — väljer automatiskt Garage (produktion) eller MinIO (lokal)

---

## Steg 7 — api/main.py

Skapa filen `api/main.py`:

```python
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
        script = f"""\
-- Lokalt läge — ingen S3 konfigurerad
-- Host: {db_creds.host}:{db_creds.port}
-- Databas: {db_creds.database}
-- Användare: {db_creds.username}
-- Lösenord: {db_creds.password}
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
        return {"keys": [], "info": "Ingen object store konfigurerad"}
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
```

---

## Steg 8 — api/static/index.html

Skapa filen `api/static/index.html` med följande innehåll (kopiera allt):

```html
<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>DuckLake Cloud</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    :root {
      --bg: #0f1117; --surface: #1a1d27; --surface2: #242736; --border: #2e3248;
      --accent: #f5a623; --accent2: #4a9eff; --text: #e8eaf0; --muted: #8b90a8;
      --danger: #e05252; --success: #52c97e; --radius: 8px;
      --font: 'Segoe UI', system-ui, sans-serif;
    }
    body { background: var(--bg); color: var(--text); font-family: var(--font); min-height: 100vh; }
    header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 2rem;
      display: flex; align-items: center; gap: 1rem; height: 56px; }
    .logo { font-size: 1.2rem; font-weight: 700; color: var(--accent); letter-spacing: -0.5px; }
    .logo span { color: var(--text); }
    .header-right { margin-left: auto; display: flex; align-items: center; gap: 0.75rem; }
    .api-key-wrap { display: flex; align-items: center; gap: 0.5rem; }
    .api-key-wrap label { font-size: 0.8rem; color: var(--muted); white-space: nowrap; }
    .api-key-wrap input { background: var(--surface2); border: 1px solid var(--border);
      color: var(--text); border-radius: var(--radius); padding: 0.35rem 0.6rem; font-size: 0.85rem; width: 180px; }
    .badge { font-size: 0.72rem; padding: 0.2rem 0.5rem; border-radius: 999px; font-weight: 600; }
    .badge.admin { background: #f5a62322; color: var(--accent); border: 1px solid #f5a62344; }
    .badge.guest { background: #8b90a822; color: var(--muted); border: 1px solid var(--border); }
    nav { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 2rem; display: flex; gap: 0.25rem; }
    .tab { padding: 0.75rem 1.25rem; font-size: 0.9rem; cursor: pointer; color: var(--muted);
      border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s; user-select: none; }
    .tab:hover { color: var(--text); }
    .tab.active { color: var(--accent); border-bottom-color: var(--accent); }
    main { max-width: 1000px; margin: 0 auto; padding: 2rem; }
    .panel { display: none; } .panel.active { display: block; }
    .section-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.25rem; }
    .section-title { font-size: 1.1rem; font-weight: 600; }
    .btn { display: inline-flex; align-items: center; gap: 0.4rem; padding: 0.45rem 1rem;
      border-radius: var(--radius); font-size: 0.875rem; font-weight: 500; cursor: pointer;
      border: 1px solid transparent; transition: opacity 0.15s; text-decoration: none; }
    .btn:hover { opacity: 0.85; }
    .btn-primary { background: var(--accent); color: #0f1117; }
    .btn-secondary { background: var(--surface2); color: var(--text); border-color: var(--border); }
    .btn-danger { background: #e0525222; color: var(--danger); border-color: #e0525244; }
    .btn-sm { padding: 0.3rem 0.7rem; font-size: 0.8rem; }
    .table-wrap { overflow-x: auto; border-radius: var(--radius); border: 1px solid var(--border); }
    table { width: 100%; border-collapse: collapse; font-size: 0.875rem; }
    th { background: var(--surface2); color: var(--muted); font-size: 0.75rem; font-weight: 600;
      text-transform: uppercase; letter-spacing: 0.05em; padding: 0.65rem 1rem; text-align: left; border-bottom: 1px solid var(--border); }
    td { padding: 0.65rem 1rem; border-bottom: 1px solid var(--border); }
    tr:last-child td { border-bottom: none; } tr:hover td { background: var(--surface2); }
    .empty { text-align: center; padding: 3rem 1rem; color: var(--muted); border: 1px dashed var(--border); border-radius: var(--radius); }
    .empty-icon { font-size: 2.5rem; margin-bottom: 0.75rem; }
    .form-row { display: flex; gap: 0.75rem; align-items: flex-end; flex-wrap: wrap; margin-bottom: 1.5rem; }
    .form-group { display: flex; flex-direction: column; gap: 0.35rem; }
    .form-group label { font-size: 0.8rem; color: var(--muted); }
    .form-group input, .form-group select { background: var(--surface2); border: 1px solid var(--border);
      color: var(--text); border-radius: var(--radius); padding: 0.45rem 0.75rem; font-size: 0.875rem; min-width: 160px; }
    .modal-overlay { display: none; position: fixed; inset: 0; background: #00000088; z-index: 100;
      align-items: center; justify-content: center; }
    .modal-overlay.open { display: flex; }
    .modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 2rem;
      max-width: 640px; width: 90%; max-height: 90vh; overflow-y: auto; }
    .modal-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 1.25rem; }
    .script-box { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius); padding: 1rem;
      font-family: 'Consolas', monospace; font-size: 0.8rem; white-space: pre; overflow-x: auto;
      color: #a8d8a8; line-height: 1.6; margin-bottom: 1rem; }
    .modal-actions { display: flex; gap: 0.75rem; justify-content: flex-end; }
    .preview-wrap { margin-top: 1rem; } .preview-wrap .table-wrap { max-height: 320px; overflow-y: auto; }
    .alert { padding: 0.75rem 1rem; border-radius: var(--radius); font-size: 0.875rem; margin-bottom: 1rem; }
    .alert-success { background: #52c97e22; border: 1px solid #52c97e44; color: var(--success); }
    .alert-error   { background: #e0525222; border: 1px solid #e0525244; color: var(--danger); }
    .alert-info    { background: #4a9eff22; border: 1px solid #4a9eff44; color: var(--accent2); }
    .spinner { width: 18px; height: 18px; border: 2px solid var(--border); border-top-color: var(--accent);
      border-radius: 50%; animation: spin 0.7s linear infinite; display: inline-block; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .perm { font-size: 0.72rem; padding: 0.15rem 0.5rem; border-radius: 999px; font-weight: 600; }
    .perm.ro { background: #4a9eff22; color: var(--accent2); border: 1px solid #4a9eff44; }
    .perm.rw { background: #52c97e22; color: var(--success); border: 1px solid #52c97e44; }
  </style>
</head>
<body>
<header>
  <div class="logo">🦆 DuckLake <span>Cloud</span></div>
  <div class="header-right">
    <div class="api-key-wrap">
      <label>Admin API-nyckel</label>
      <input type="password" id="globalApiKey" placeholder="Lämna tom för gäst" oninput="onApiKeyChange()" />
    </div>
    <span class="badge guest" id="roleBadge">Gäst</span>
  </div>
</header>
<nav>
  <div class="tab active" onclick="switchTab('datasets')">📦 Datasets</div>
  <div class="tab" onclick="switchTab('access-keys')">🔑 Access-nycklar</div>
</nav>
<main>
  <div class="panel active" id="panel-datasets">
    <div id="datasets-alert"></div>
    <div class="section-header">
      <div class="section-title">Datasets i lake</div>
      <button class="btn btn-primary btn-sm" onclick="openUploadModal()">+ Ladda upp dataset</button>
    </div>
    <div id="datasets-list"><div class="spinner"></div></div>
  </div>
  <div class="panel" id="panel-access-keys">
    <div id="keys-alert"></div>
    <div class="section-title" style="margin-bottom:1.25rem">Generera access-nyckel</div>
    <div class="form-row">
      <div class="form-group">
        <label>Användarnamn</label>
        <input type="text" id="keyUsername" placeholder="t.ex. student1" />
      </div>
      <div class="form-group">
        <label>Behörighet</label>
        <select id="keyPermission">
          <option value="readonly">Read-only</option>
          <option value="readwrite">Read/Write (kräver admin-nyckel)</option>
        </select>
      </div>
      <div class="form-group">
        <label>&nbsp;</label>
        <button class="btn btn-primary" onclick="createKey()">Generera nyckel</button>
      </div>
    </div>
    <div class="section-header" style="margin-top:1.5rem">
      <div class="section-title">Befintliga nycklar</div>
      <button class="btn btn-secondary btn-sm" onclick="loadKeys()">↻ Uppdatera</button>
    </div>
    <div id="keys-list">
      <div class="alert alert-info">Ange admin API-nyckel i headern för att lista befintliga nycklar.</div>
    </div>
  </div>
</main>

<div class="modal-overlay" id="uploadModal">
  <div class="modal">
    <div class="modal-title">Ladda upp dataset</div>
    <div id="upload-alert"></div>
    <div class="form-group" style="margin-bottom:0.75rem">
      <label>Tabellnamn</label>
      <input type="text" id="uploadTableName" placeholder="t.ex. mina_data" />
    </div>
    <div class="form-group" style="margin-bottom:1.25rem">
      <label>Fil (CSV eller Parquet)</label>
      <input type="file" id="uploadFile" accept=".csv,.parquet" style="background:none;border:none;padding:0;color:var(--text)" />
    </div>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeModal('uploadModal')">Avbryt</button>
      <button class="btn btn-primary" onclick="uploadDataset()">Ladda upp</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="previewModal">
  <div class="modal" style="max-width:800px">
    <div class="modal-title" id="previewTitle">Förhandsvisning</div>
    <div class="preview-wrap" id="previewContent"></div>
    <div class="modal-actions" style="margin-top:1rem">
      <button class="btn btn-secondary" onclick="closeModal('previewModal')">Stäng</button>
    </div>
  </div>
</div>

<div class="modal-overlay" id="keyModal">
  <div class="modal">
    <div class="modal-title">🔑 Access-nyckel skapad</div>
    <div class="alert alert-success" style="margin-bottom:1rem">
      Spara skriptet nedan — lösenorden visas bara en gång!
    </div>
    <div class="script-box" id="keyScript"></div>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="copyScript()">📋 Kopiera</button>
      <button class="btn btn-primary" onclick="closeModal('keyModal')">Klar</button>
    </div>
  </div>
</div>

<script>
const apiKey = () => document.getElementById('globalApiKey').value.trim();
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t, i) => t.classList.toggle('active', ['datasets','access-keys'][i] === name));
  document.querySelectorAll('.panel').forEach(p => p.classList.toggle('active', p.id === `panel-${name}`));
  if (name === 'datasets') loadDatasets();
  if (name === 'access-keys' && apiKey()) loadKeys();
}
function onApiKeyChange() {
  const isAdmin = apiKey().length > 0;
  const badge = document.getElementById('roleBadge');
  badge.textContent = isAdmin ? 'Admin' : 'Gäst';
  badge.className = `badge ${isAdmin ? 'admin' : 'guest'}`;
  if (isAdmin) loadKeys();
}
async function api(method, path, body, isForm) {
  const headers = {};
  if (apiKey()) headers['X-Api-Key'] = apiKey();
  const opts = { method, headers };
  if (body && !isForm) { headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  else if (body && isForm) { opts.body = body; }
  const res = await fetch(path, opts);
  if (!res.ok) { const err = await res.json().catch(() => ({ detail: res.statusText })); throw new Error(err.detail || res.statusText); }
  return res.json();
}
function showAlert(id, msg, type = 'error') { document.getElementById(id).innerHTML = `<div class="alert alert-${type}">${msg}</div>`; }
function clearAlert(id) { document.getElementById(id).innerHTML = ''; }
function openModal(id) { document.getElementById(id).classList.add('open'); }
function closeModal(id) { document.getElementById(id).classList.remove('open'); }
function openUploadModal() {
  if (!apiKey()) { showAlert('datasets-alert','Ange admin API-nyckel för att ladda upp.'); return; }
  clearAlert('upload-alert');
  document.getElementById('uploadTableName').value = '';
  document.getElementById('uploadFile').value = '';
  openModal('uploadModal');
}
async function loadDatasets() {
  const el = document.getElementById('datasets-list');
  clearAlert('datasets-alert');
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const data = await api('GET', '/api/datasets');
    if (!data.length) { el.innerHTML = `<div class="empty"><div class="empty-icon">📭</div>Inga datasets ännu.</div>`; return; }
    el.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Dataset</th><th>Åtgärder</th></tr></thead><tbody>
      ${data.map(d => `<tr><td><strong>${d.namn}</strong></td><td style="display:flex;gap:0.5rem">
        <button class="btn btn-secondary btn-sm" onclick="previewDataset('${d.namn}')">👁 Visa</button>
        <button class="btn btn-danger btn-sm" onclick="deleteDataset('${d.namn}')">🗑 Radera</button></td></tr>`).join('')}
    </tbody></table></div>`;
  } catch (e) { el.innerHTML = `<div class="alert alert-error">Kunde inte hämta datasets: ${e.message}</div>`; }
}
async function previewDataset(namn) {
  document.getElementById('previewTitle').textContent = `📦 ${namn}`;
  document.getElementById('previewContent').innerHTML = '<div class="spinner"></div>';
  openModal('previewModal');
  try {
    const d = await api('GET', `/api/datasets/${namn}?limit=50`);
    if (!d.data.length) { document.getElementById('previewContent').innerHTML = '<div class="alert alert-info">Tabellen är tom.</div>'; return; }
    document.getElementById('previewContent').innerHTML = `<div class="table-wrap"><table>
      <thead><tr>${d.kolumner.map(k => `<th>${k}</th>`).join('')}</tr></thead>
      <tbody>${d.data.map(r => `<tr>${d.kolumner.map(k => `<td>${r[k] ?? ''}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div><p style="font-size:0.8rem;color:var(--muted);margin-top:0.5rem">Visar max 50 rader</p>`;
  } catch (e) { document.getElementById('previewContent').innerHTML = `<div class="alert alert-error">${e.message}</div>`; }
}
async function deleteDataset(namn) {
  if (!apiKey()) { showAlert('datasets-alert','Ange admin API-nyckel för att radera.'); return; }
  if (!confirm(`Radera dataset "${namn}"?`)) return;
  try { await api('DELETE', `/api/datasets/${namn}`); showAlert('datasets-alert', `Dataset "${namn}" raderades.`, 'success'); loadDatasets(); }
  catch (e) { showAlert('datasets-alert', `Fel: ${e.message}`); }
}
async function uploadDataset() {
  const tabellnamn = document.getElementById('uploadTableName').value.trim();
  const fil = document.getElementById('uploadFile').files[0];
  clearAlert('upload-alert');
  if (!tabellnamn) { showAlert('upload-alert','Ange ett tabellnamn.'); return; }
  if (!fil) { showAlert('upload-alert','Välj en fil.'); return; }
  const fd = new FormData(); fd.append('fil', fil); fd.append('tabellnamn', tabellnamn);
  try { await api('POST', '/api/datasets/upload', fd, true); closeModal('uploadModal'); showAlert('datasets-alert', `Dataset "${tabellnamn}" laddades upp!`, 'success'); loadDatasets(); }
  catch (e) { showAlert('upload-alert', `Uppladdning misslyckades: ${e.message}`); }
}
async function createKey() {
  const username = document.getElementById('keyUsername').value.trim();
  const permission = document.getElementById('keyPermission').value;
  clearAlert('keys-alert');
  if (!username) { showAlert('keys-alert','Ange ett användarnamn.'); return; }
  try {
    const res = await api('POST', '/api/access-keys', { username, permission });
    document.getElementById('keyScript').textContent = res.duckdb_script || '-- Inget script genererat';
    openModal('keyModal'); loadKeys();
  } catch (e) { showAlert('keys-alert', `Kunde inte skapa nyckel: ${e.message}`); }
}
async function loadKeys() {
  const el = document.getElementById('keys-list');
  if (!apiKey()) { el.innerHTML = '<div class="alert alert-info">Ange admin API-nyckel för att lista befintliga nycklar.</div>'; return; }
  el.innerHTML = '<div class="spinner"></div>';
  try {
    const data = await api('GET', '/api/access-keys');
    const keys = data.keys || [];
    if (!keys.length) { el.innerHTML = `<div class="empty"><div class="empty-icon">🔑</div>Inga nycklar skapade ännu.</div>`; return; }
    el.innerHTML = `<div class="table-wrap"><table><thead><tr><th>Key ID / Användare</th><th>Behörighet</th><th>Åtgärd</th></tr></thead><tbody>
      ${keys.map(k => `<tr><td><code style="font-size:0.85rem">${k.key_id}</code></td>
        <td><span class="perm ${k.permission === 'readwrite' ? 'rw' : 'ro'}">${k.permission}</span></td>
        <td><button class="btn btn-danger btn-sm" onclick="revokeKey('${k.key_id}')">Återkalla</button></td></tr>`).join('')}
    </tbody></table></div>`;
  } catch (e) { el.innerHTML = `<div class="alert alert-error">Kunde inte hämta nycklar: ${e.message}</div>`; }
}
async function revokeKey(keyId) {
  if (!confirm(`Återkalla nyckel "${keyId}"?`)) return;
  try { await api('DELETE', `/api/access-keys/${keyId}`); showAlert('keys-alert', `Nyckel "${keyId}" återkallades.`, 'success'); loadKeys(); }
  catch (e) { showAlert('keys-alert', `Fel: ${e.message}`); }
}
function copyScript() {
  navigator.clipboard.writeText(document.getElementById('keyScript').textContent)
    .then(() => showAlert('keys-alert','Kopierat!', 'success'));
}
loadDatasets();
</script>
</body>
</html>
```

---

## Steg 9 — Starta systemet

I terminalen, från projektmappen:

```bash
docker compose up --build
```

Första gången tar det ca 3–5 minuter — Docker laddar ner images och installerar DuckDB-tillägg. Du ser att det är klart när du ser:

```
api-1  | INFO:     Application startup complete.
api-1  | INFO:     Uvicorn running on http://0.0.0.0:8000
```

Öppna sedan: **http://localhost:8000**

---

## Steg 10 — Verifiera att allt fungerar

### Kontrollera att du ser frontenden
Öppna `http://localhost:8000` — du ska se en mörk webbsida med två flikar: **Datasets** och **Access-nycklar**.

Under **Datasets** ska du direkt se tre tabeller: `kunder`, `produkter`, `ordrar`.

Klicka **👁 Visa** på `kunder` — du ska se tre förifyllda rader.

### Kontrollera API:et direkt
Öppna `http://localhost:8000/docs` för att se alla endpoints i Swagger UI.

### Testa admin-funktioner
Ange API-nyckeln `change-me` i fältet **Admin API-nyckel** uppe till höger — du ska se att det ändras till **Admin**.

Nu kan du:
- Ladda upp en CSV-fil (klicka **+ Ladda upp dataset**)
- Radera datasets

---

## Steg 11 — Testa access-nycklar

1. Gå till fliken **Access-nycklar**
2. Skriv in ett användarnamn, t.ex. `student1`
3. Välj **Read-only**
4. Klicka **Generera nyckel**
5. En popup visas med ett färdigt DuckDB-script

> **OBS (lokalt):** Scriptet innehåller `minio:9000` som S3-endpoint. Det är den interna Docker-adressen. Om du vill använda scriptet utanför Docker behöver du ändra till `localhost:9002` och PostgreSQL-host till `localhost`.

---

## Steg 12 — Stoppa systemet

```bash
# Stoppa (behåller datan)
docker compose down

# Stoppa och rensa all data (börja om från noll)
docker compose down -v
```

---

## Felsökning

| Problem | Lösning |
|---------|---------|
| Port 8000 är redan i bruk | Ändra `"8000:8000"` till `"8001:8000"` i docker-compose.yml |
| MinIO-port 9002/9003 i bruk | Ändra till `"9004:9000"` och `"9005:9001"` |
| API startar inte | Kör `docker compose logs api` och läs felmeddelandet |
| Datan försvann | Se till att `volumes:` finns i docker-compose.yml |
| "Internal Server Error" | Kör `docker compose logs api --tail=50` för detaljer |

---

## Nästa steg — Deploya till KTH Cloud

När systemet fungerar lokalt kan du följa [GUIDE.md](../GUIDE.md) för att deploya till KTH Cloud med tre separata deployments (PostgreSQL, MinIO, API).

Källkod och referensimplementation: [github.com/Mahdiwolfs/ducklake-cloud](https://github.com/Mahdiwolfs/ducklake-cloud)
