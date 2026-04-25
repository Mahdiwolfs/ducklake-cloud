# Modul 06 — Access-nycklar och behörigheter

## Vad du lär dig
- Varför DuckLake behöver två typer av nycklar (S3 + PostgreSQL)
- Hur du begär en access-nyckel via API:et
- Hur du kopplar upp DuckDB mot en central lake med nyckeln
- Skillnaden mellan read-only och read/write

---

## Bakgrund

När DuckLake körs centralt (på KTH Cloud) är PostgreSQL och MinIO/Garage privata — de är inte tillgängliga direkt från internet. Alla studenter och ML-användare som vill läsa data måste autentisera sig.

Systemet löser detta med **access-nyckelpar**:

| Komponent | Vad nyckeln ger access till |
|---|---|
| **S3-nyckel** | Parquet-filerna i MinIO/Garage (själva datat) |
| **PostgreSQL-användare** | DuckLakes metadatakatalog (tabellnamn, schema, snapshots) |

Du behöver **båda** för att kunna ansluta med DuckDB.

---

## Behörighetsnivåer

| Typ | Vad man kan göra | Kräver |
|---|---|---|
| **read-only** | `SELECT` — läsa data | Inget (öppen begäran) |
| **read/write** | `SELECT`, `INSERT`, `UPDATE`, `DELETE` | Admin API-nyckel |

---

## Steg 1 — Begär en access-nyckel

### Via webbfrontenden (enklast)
Gå till `http://localhost:8000` → fliken **Access-nycklar**.

Fyll i ett användarnamn och välj behörighet, klicka **Generera nyckel**.  
Du får ett DuckDB-script att kopiera direkt.

### Via API:et (cURL)

**Read-only** (ingen API-nyckel krävs):
```bash
curl -X POST http://localhost:8000/api/access-keys \
  -H "Content-Type: application/json" \
  -d '{"username": "student1", "permission": "readonly"}'
```

**Read/Write** (kräver admin-nyckel):
```bash
curl -X POST http://localhost:8000/api/access-keys \
  -H "Content-Type: application/json" \
  -H "X-Api-Key: change-me" \
  -d '{"username": "student1", "permission": "readwrite"}'
```

Svaret innehåller fältet `duckdb_script` — ett färdigt script du kan klistra in i DuckDB.

---

## Steg 2 — Anslut med DuckDB

Klistra in scriptet från svaret i DuckDB CLI eller en Jupyter-cell:

```sql
INSTALL ducklake;
INSTALL postgres;
INSTALL httpfs;

LOAD ducklake;
LOAD postgres;
LOAD httpfs;

-- PostgreSQL-katalog
CREATE OR REPLACE SECRET pg_secret (
    TYPE     postgres,
    HOST     'localhost',      -- byt till serveradressen i prod
    PORT     5432,
    DATABASE 'ducklake',
    USER     'student1',       -- ditt användarnamn
    PASSWORD 'genererat-lösenord'
);

-- S3/MinIO-lagring
CREATE OR REPLACE SECRET s3_secret (
    TYPE      s3,
    PROVIDER  config,
    KEY_ID    'student1',      -- ditt Key ID
    SECRET    'genererat-secret',
    REGION    'local',
    ENDPOINT  'localhost:9000', -- byt till serveradressen i prod
    URL_STYLE 'path',
    USE_SSL   false
);

-- Anslut!
ATTACH 'ducklake:postgres:dbname=ducklake' AS lake (DATA_PATH 's3://ducklake/');

-- Testa:
SHOW TABLES FROM lake;
SELECT * FROM lake.kunder LIMIT 5;
```

---

## Steg 3 — Anslut med Python

```python
import duckdb

con = duckdb.connect()
con.execute("INSTALL ducklake; LOAD ducklake")
con.execute("INSTALL postgres;  LOAD postgres")
con.execute("INSTALL httpfs;    LOAD httpfs")

con.execute("""
    CREATE OR REPLACE SECRET pg_secret (
        TYPE postgres, HOST 'localhost', PORT 5432,
        DATABASE 'ducklake', USER 'student1', PASSWORD 'genererat-lösenord'
    )
""")
con.execute("""
    CREATE OR REPLACE SECRET s3_secret (
        TYPE s3, PROVIDER config,
        KEY_ID 'student1', SECRET 'genererat-secret',
        REGION 'local', ENDPOINT 'localhost:9000',
        URL_STYLE 'path', USE_SSL false
    )
""")
con.execute("ATTACH 'ducklake:postgres:dbname=ducklake' AS lake (DATA_PATH 's3://ducklake/')")

result = con.execute("SELECT * FROM lake.kunder LIMIT 10").fetchdf()
print(result)
```

---

## Steg 4 — Anslut med Java (JDBC)

```java
// Samma som tidigare men med studentens credentials
String duckUrl = "jdbc:duckdb:";
try (Connection conn = DriverManager.getConnection(duckUrl);
     Statement stmt = conn.createStatement()) {

    stmt.execute("INSTALL ducklake; LOAD ducklake");
    stmt.execute("INSTALL postgres;  LOAD postgres");
    stmt.execute("INSTALL httpfs;    LOAD httpfs");

    stmt.execute("""
        CREATE OR REPLACE SECRET pg_secret (
            TYPE postgres, HOST 'localhost', PORT 5432,
            DATABASE 'ducklake', USER 'student1', PASSWORD 'genererat-lösenord'
        )""");

    stmt.execute("""
        CREATE OR REPLACE SECRET s3_secret (
            TYPE s3, PROVIDER config,
            KEY_ID 'student1', SECRET 'genererat-secret',
            REGION 'local', ENDPOINT 'localhost:9000',
            URL_STYLE 'path', USE_SSL false
        )""");

    stmt.execute("ATTACH 'ducklake:postgres:dbname=ducklake' AS lake (DATA_PATH 's3://ducklake/')");

    ResultSet rs = stmt.executeQuery("SELECT * FROM lake.kunder LIMIT 10");
    while (rs.next()) {
        System.out.println(rs.getString("namn"));
    }
}
```

---

## Lista och återkalla nycklar (admin)

```bash
# Lista alla nycklar
curl http://localhost:8000/api/access-keys \
  -H "X-Api-Key: change-me"

# Återkalla en nyckel
curl -X DELETE http://localhost:8000/api/access-keys/student1 \
  -H "X-Api-Key: change-me"
```

---

## Byta från MinIO till Garage (produktion)

Systemet är byggt med ett interface-mönster (`ObjectStoreAccessTokenManager`) som gör det enkelt att byta backend. I produktion används **Garage** istället för MinIO.

Sätt miljövariablerna i docker-compose.yml (eller KTH Cloud):
```yaml
GARAGE_ADMIN_URL:   http://garage:3903
GARAGE_ADMIN_TOKEN: <din-admin-token>
```

Applikationen väljer automatiskt Garage om `GARAGE_ADMIN_URL` är satt, annars MinIO.

---

## Övningar → `laxor/06-laxor.md`
