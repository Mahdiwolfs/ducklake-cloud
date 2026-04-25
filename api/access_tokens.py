import json
import os
import secrets
import string
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
    """Hanterar access-nycklar via MinIO Admin API."""

    def __init__(self, endpoint: str, admin_key: str, admin_secret: str, bucket: str):
        from minio import MinioAdmin
        self._admin = MinioAdmin(endpoint, access_key=admin_key, secret_key=admin_secret, secure=False)
        self._endpoint = endpoint
        self._bucket = bucket
        for name, policy in [("ducklake-ro", _POLICY_READONLY), ("ducklake-rw", _POLICY_READWRITE)]:
            try:
                self._admin.add_policy(name, policy)
            except Exception:
                pass

    def create_key(self, username: str, permission: str) -> ObjectStoreKey:
        secret = _rand()
        self._admin.add_user(username, secret)
        self._admin.set_policy("ducklake-ro" if permission == "readonly" else "ducklake-rw", user=username)
        return ObjectStoreKey(key_id=username, secret=secret,
                              permission=permission, endpoint=self._endpoint,
                              bucket=self._bucket)

    def revoke_key(self, key_id: str) -> None:
        self._admin.remove_user(key_id)

    def list_keys(self) -> list[dict]:
        try:
            users = self._admin.list_users()
            return [
                {"key_id": ak, "permission": "readwrite" if info.get("policyName") == "ducklake-rw" else "readonly"}
                for ak, info in users.items()
            ]
        except Exception:
            return []


# ── GARAGE IMPLEMENTATION ─────────────────────────────────────────────────────

class GarageAccessTokenManager(ObjectStoreAccessTokenManager):
    """
    Hanterar access-nycklar via Garage Admin REST API (standard port 3903).
    Används i produktion — MinIO är deprecated.
    Docs: https://garagehq.deuxfleurs.fr/documentation/reference-manual/admin-api/
    """

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
    """Skapar och tar bort PostgreSQL-användare för DuckLake-katalogåtkomst."""

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
                # Ge access till alla schemas (DuckLake skapar egna schemas i postgres)
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
    """Genererar ett färdigt DuckDB-script för att ansluta till DuckLake."""
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
    """Returnerar rätt implementation baserat på miljövariabler."""
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
