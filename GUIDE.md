# Komplett guide: DuckLake på KTH Cloud

## Innehåll

1. [Vad är DuckLake?](#vad-är-ducklake)
2. [Varför DuckLake?](#varför-ducklake)
3. [Arkitektur och infrastruktur](#arkitektur)
4. [Skapa infrastrukturen på KTH Cloud](#skapa-infrastrukturen)
5. [Python API](#python-api)
6. [Java API](#java-api)
7. [Vanliga fällor och hur man undviker dem](#fällor)

---

## Vad är DuckLake?

DuckLake är ett **lakehouse-format** byggt ovanpå DuckDB. Det separerar data i två delar:

### Katalog
Lagrar **metadata** — information om vilka tabeller som finns, hur de ser ut (schema), och en historik av alla ändringar (snapshots). I en produktionssättning lagras katalogen i **PostgreSQL**.

### Parquet-filer
Den faktiska datan lagras som **Parquet-filer** — ett öppet kolumnformat som kan läsas av Python, Java, Spark, Pandas och många fler verktyg. I en produktionssättning lagras filerna i **MinIO** (S3-kompatibel objekt-lagring).

### Time travel
Varje skrivoperation skapar en ny **snapshot**. Det innebär att du kan läsa historiska versioner av datan — om du av misstag raderar data kan du gå tillbaka i tiden och hämta den.

```
DuckLake = PostgreSQL (katalog) + MinIO (Parquet-filer)
```

---

## Varför DuckLake?

| Egenskap | DuckLake | PostgreSQL |
|----------|----------|------------|
| Kräver server | Nej (filer) | Ja |
| Dataformat | Parquet (öppet) | Binärt (proprietärt) |
| Time travel | Ja | Nej |
| Kan läsas av | Python, Java, Spark, Pandas... | Kräver PostgreSQL-klient |
| Skalbarhet | S3/GCS/lokal disk | Begränsad |

DuckLake passar bäst när:
- Du vill lagra stora mängder data som filer
- Flera olika program och språk ska läsa datan
- Du vill ha historik och time travel
- Du inte vill vara bunden till ett proprietärt format

---

## Arkitektur

```
Klient (Python/Java)
        ↓ HTTP
   FastAPI / Spring Boot  ←── PORT 8000/8080
        ↓ duckdb / JDBC
      DuckLake
      ↙        ↘
PostgreSQL    MinIO
(katalog)   (Parquet)
PORT 5432   PORT 9000
```

Klienter pratar **aldrig** direkt med PostgreSQL eller MinIO — de kommunicerar alltid via API:et.

---

## Skapa infrastrukturen

Du behöver tre deployments på KTH Cloud i **denna ordning**:
1. PostgreSQL (katalog)
2. MinIO (lagring)
3. API (Python eller Java)

### Deployment 1 — PostgreSQL

**Image:** `postgres:16-alpine`  
**Port:** `5432`  
**Visibility:** `Private` ← viktigt! PostgreSQL ska inte vara publik.

#### Miljövariabler

| Variabel | Värde | Förklaring |
|----------|-------|------------|
| `POSTGRES_DB` | `ducklake` | Skapar en databas med detta namn automatiskt vid start |
| `POSTGRES_USER` | `duck` | Användarnamnet som API:et ansluter med |
| `POSTGRES_PASSWORD` | `<lösenord>` | Välj ett starkt lösenord |

#### Persistent storage

PostgreSQL lagrar sin data i `/var/lib/postgresql/data`. Utan persistent storage försvinner **all data** varje gång containern startas om.

| Fält | Värde |
|------|-------|
| Name | `postgres-data` |
| App path | `/var/lib/postgresql/data` |
| Storage path | `/<valfritt-namn>` |

#### Vad du kan förvänta dig i loggen

```
LOG: database system is ready to accept connections
LOG: listening on IPv4 address "0.0.0.0", port 5432
```

> **OBS:** Du kommer se `502 Bad Gateway` i KTH Cloud — det är **normalt**. KTH Clouds hälsokontroll skickar HTTP-anrop till port 5432, men PostgreSQL pratar inte HTTP. Det påverkar inte funktionen.

---

### Deployment 2 — MinIO

**Image:** `minio/minio`  
**Port:** `9000`  
**Visibility:** `Private`  
**Image start arguments:** `server /data` ← **glöm inte detta!**

#### Miljövariabler

| Variabel | Värde | Förklaring |
|----------|-------|------------|
| `MINIO_ROOT_USER` | `minioadmin` | Användarnamn för MinIO |
| `MINIO_ROOT_PASSWORD` | `<lösenord>` | Välj ett starkt lösenord |

#### Persistent storage

MinIO lagrar Parquet-filerna i `/data`. Utan persistent storage försvinner alla uppladdade dataset.

| Fält | Värde |
|------|-------|
| Name | `minio-data` |
| App path | `/data` |
| Storage path | `/<valfritt-namn>` |

#### Health check

KTH Clouds standardhälsokontroll på `/healthz` fungerar **inte** för MinIO. Ändra till:

```
/minio/health/live
```

Annars startar inte containern korrekt.

---

### Deployment 3 — API

Se Python API eller Java API nedan.

---

## Python API

### Hur Python ansluter till DuckLake

Python ansluter **direkt** till DuckLake via `duckdb`-biblioteket. FastAPI fungerar som ett HTTP-lager ovanpå.

```
HTTP-anrop → FastAPI → duckdb-bibliotek → DuckLake (PostgreSQL + MinIO)
```

### database.py — anslutningslogiken

```python
import duckdb
import os

POSTGRES_HOST     = os.getenv("POSTGRES_HOST",     "localhost")
POSTGRES_PORT     = os.getenv("POSTGRES_PORT",     "5432")
POSTGRES_DB       = os.getenv("POSTGRES_DB",       "ducklake")
POSTGRES_USER     = os.getenv("POSTGRES_USER",     "duck")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_KEY_ID   = os.getenv("S3_KEY_ID",   "minioadmin")
S3_SECRET   = os.getenv("S3_SECRET",   "minioadmin")
S3_BUCKET   = os.getenv("S3_BUCKET",   "ducklake")

def get_conn():
    con = duckdb.connect()
    con.execute("LOAD ducklake")
    con.execute("LOAD postgres")

    # Skapa en "secret" med PostgreSQL-anslutningsdetaljer
    con.execute(f"""
        CREATE OR REPLACE SECRET (
            TYPE postgres,
            HOST '{POSTGRES_HOST}',
            PORT {POSTGRES_PORT},
            DATABASE '{POSTGRES_DB}',
            USER '{POSTGRES_USER}',
            PASSWORD '{POSTGRES_PASSWORD}'
        )
    """)

    if S3_ENDPOINT:
        con.execute("LOAD httpfs")
        con.execute(f"""
            CREATE OR REPLACE SECRET (
                TYPE s3,
                KEY_ID '{S3_KEY_ID}',
                SECRET '{S3_SECRET}',
                ENDPOINT '{S3_ENDPOINT}',
                URL_STYLE 'path',
                USE_SSL false
            )
        """)
        data_path = f"s3://{S3_BUCKET}/"
    else:
        data_path = "./data/lake/"

    # Koppla ihop katalogen (PostgreSQL) med lagringen (MinIO/disk)
    con.execute(f"""
        ATTACH 'ducklake:postgres:dbname={POSTGRES_DB}'
        AS lake (DATA_PATH '{data_path}')
    """)
    return con
```

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Installera DuckDB-extensions i förväg för snabbare start
RUN python3 -c "import duckdb; con = duckdb.connect(); \
    con.execute('INSTALL ducklake'); \
    con.execute('INSTALL postgres'); \
    con.execute('INSTALL httpfs')"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### requirements.txt

```
fastapi==0.136.0
uvicorn==0.44.0
duckdb==1.5.2
minio==7.2.15
python-multipart==0.0.20
```

### Deployment av Python API på KTH Cloud

**Image:** `ghcr.io/<användarnamn>/<repo>:latest`  
**Port:** `8000`  
**Visibility:** `Public`

#### Miljövariabler

| Variabel | Värde | Varför |
|----------|-------|--------|
| `POSTGRES_HOST` | `<postgresql-deployment-namn>` | KTH Cloud löser upp deployment-namn som DNS-adresser internt |
| `POSTGRES_PORT` | `5432` | PostgreSQLs standardport |
| `POSTGRES_DB` | `ducklake` | Samma som du satte i deployment 1 |
| `POSTGRES_USER` | `duck` | Samma som du satte i deployment 1 |
| `POSTGRES_PASSWORD` | `<lösenord>` | Samma som du satte i deployment 1 |
| `S3_ENDPOINT` | `<minio-deployment-namn>:9000` | Utan `http://` — duckdb lägger till det |
| `S3_KEY_ID` | `minioadmin` | Samma som du satte i deployment 2 |
| `S3_SECRET` | `<lösenord>` | Samma som du satte i deployment 2 |
| `S3_BUCKET` | `ducklake` | Bucket-namn — skapas automatiskt vid första start |
| `API_KEY` | `<valfritt lösenord>` | Skyddar POST/DELETE-endpoints |

---

## Java API

### Hur Java ansluter till DuckLake

Java ansluter **direkt** till DuckLake via DuckDB JDBC-drivrutinen. Spring Boot fungerar som HTTP-lager.

```
HTTP-anrop → Spring Boot → DuckDB JDBC → DuckLake (PostgreSQL + MinIO)
```

Det finns **ingen Python-mellanhand** — Java pratar direkt med databasen.

### pom.xml — viktig detalj om versionen

DuckDB publicerar sin JDBC-drivrutin på Maven Central med ett **fyrsiffrigt versionsnummer**:

```xml
<dependency>
    <groupId>org.duckdb</groupId>
    <artifactId>duckdb_jdbc</artifactId>
    <version>1.5.2.0</version>  <!-- INTE 1.5.2 — det finns inte! -->
</dependency>
```

Kontrollera alltid rätt version på:
```
https://search.maven.org/search?q=g:org.duckdb+a:duckdb_jdbc
```

### DuckLakeService.java — anslutningslogiken

```java
@PostConstruct
public void installExtensions() throws SQLException {
    // Installera extensions en gång vid start
    try (Connection conn = DriverManager.getConnection("jdbc:duckdb:");
         Statement stmt = conn.createStatement()) {
        stmt.execute("INSTALL ducklake");
        stmt.execute("INSTALL postgres");
        stmt.execute("INSTALL httpfs");
    }
}

public Connection openConnection() throws SQLException {
    Connection conn = DriverManager.getConnection("jdbc:duckdb:");
    try (Statement stmt = conn.createStatement()) {
        stmt.execute("LOAD ducklake");
        stmt.execute("LOAD postgres");

        // Skapa secret med anslutningsdetaljer
        // OBS: PORT måste vara ett heltal, inte en sträng
        stmt.execute("""
            CREATE OR REPLACE SECRET (
                TYPE postgres,
                HOST '%s',
                PORT 5432,
                DATABASE '%s',
                USER '%s',
                PASSWORD '%s'
            )""".formatted(pgHost, pgDb, pgUser, pgPass));

        // Koppla DuckLake till PostgreSQL-katalogen
        stmt.execute("ATTACH 'ducklake:postgres:dbname=" + pgDb 
            + "' AS lake (DATA_PATH 's3://" + s3Bucket + "/')");
    }
    return conn;
}
```

### application.properties

```properties
server.port=8080
# Använd ducklake.* prefix för att undvika konflikter med Spring Boot
ducklake.postgres.host=${POSTGRES_HOST:localhost}
ducklake.postgres.db=${POSTGRES_DB:ducklake}
ducklake.postgres.user=${POSTGRES_USER:duck}
ducklake.postgres.password=${POSTGRES_PASSWORD:postgres}
ducklake.s3.endpoint=${S3_ENDPOINT:}
ducklake.s3.keyid=${S3_KEY_ID:minioadmin}
ducklake.s3.secret=${S3_SECRET:minioadmin}
ducklake.s3.bucket=${S3_BUCKET:ducklake}
ducklake.s3.region=${S3_REGION:local}
ducklake.api.key=${API_KEY:change-me}
```

### Dockerfile

```dockerfile
FROM eclipse-temurin:21-jdk-jammy AS build
WORKDIR /app
RUN apt-get update && apt-get install -y maven && rm -rf /var/lib/apt/lists/*
COPY pom.xml .
RUN mvn dependency:go-offline -q
COPY src ./src
RUN mvn package -DskipTests -q

FROM eclipse-temurin:21-jre-jammy
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE 8080
CMD ["java", "-jar", "app.jar"]
```

### Deployment av Java API på KTH Cloud

**Image:** `ghcr.io/<användarnamn>/<repo>/java-api:latest`  
**Port:** `8080`  
**Visibility:** `Public`

#### Miljövariabler

| Variabel | Värde | Varför |
|----------|-------|--------|
| `POSTGRES_HOST` | `<postgresql-deployment-namn>` | Deployment-namn fungerar som intern DNS |
| `POSTGRES_DB` | `ducklake` | Databasnamnet |
| `POSTGRES_USER` | `duck` | Användaren |
| `POSTGRES_PASSWORD` | `<lösenord>` | Lösenordet |
| `S3_ENDPOINT` | `<minio-deployment-namn>:9000` | MinIO-adressen |
| `S3_KEY_ID` | `minioadmin` | MinIO-användaren |
| `S3_SECRET` | `<lösenord>` | MinIO-lösenordet |
| `S3_BUCKET` | `ducklake` | Bucket-namn |
| `API_KEY` | `<valfritt lösenord>` | Skyddar skrivoperationer |
| `PORT` | `8080` | Porten Spring Boot lyssnar på |

---

## Fällor

### 1. POSTGRES_PORT skrivs över av Kubernetes

**Problemet:** I Kubernetes injiceras service-variabler automatiskt som miljövariabler i alla pods. Om det finns en service med ett namn som innehåller "postgres" i namespacet sätts `POSTGRES_PORT=tcp://IP:PORT` automatiskt — och skriver över ditt värde `5432`.

**Symtom:**
```
Parser Error: syntax error at or near ":"
LINE 4: PORT tcp://10.43.82.64:5432,
```

**Lösning för Java:** Hårdkoda `PORT 5432` direkt i SQL-strängen istället för att läsa från miljövariabel:
```java
stmt.execute("... PORT 5432, ...");
```

**Lösning för Python:** Om problemet uppstår, byt variabelnamn från `POSTGRES_PORT` till `PG_PORT` eller läs porten från ett annat variabelnamn.

---

### 2. MinIO health check fungerar inte

**Problemet:** KTH Cloud kontrollerar `/healthz` som standard, men MinIO har inte den endpoint.

**Symtom:** Deploymentet fastnar i "Creating" utan loggar.

**Lösning:** Ändra health check-sökvägen till:
```
/minio/health/live
```

---

### 3. Fel DuckDB JDBC-version

**Problemet:** DuckDB använder fyrsiffriga versionsnummer på Maven Central. `1.2.2` finns inte — det heter `1.2.2.0`.

**Symtom:**
```
Could not find artifact org.duckdb:duckdb_jdbc:jar:1.2.2 in central
```

**Lösning:** Kontrollera exakt version på Maven Central och använd fyrsiffrigt format: `1.5.2.0`

---

### 4. DuckLake-extensionen saknas för din DuckDB-version

**Problemet:** DuckLake-extensionen är inte tillgänglig för äldre DuckDB-versioner.

**Symtom:**
```
HTTP Error: Failed to download extension "ducklake" at URL ".../v1.2.2/..." (HTTP 404)
Candidate extensions: "delta", "excel", "azure"...
```

**Lösning:** Uppgradera till DuckDB 1.3.0+ (JDBC: `1.3.0.0` eller senare).

---

### 5. Cirkulär referens i application.properties

**Problemet:** Om du skriver `S3_REGION=${S3_REGION:local}` i application.properties tolkar Spring Boot det som en cirkulär referens.

**Symtom:**
```
Circular placeholder reference 'S3_REGION:local' in property definitions
```

**Lösning:** Använd Spring-stil med eget prefix:
```properties
# FEL:
S3_REGION=${S3_REGION:local}

# RÄTT:
ducklake.s3.region=${S3_REGION:local}
```

---

### 6. Kolon i SQL-strängar med DuckDB JDBC

**Problemet:** DuckDB JDBC kan tolka `:` i SQL-strängar som namngivna parametrar, vilket ger syntaxfel.

**Symtom:**
```
Parser Error: syntax error at or near ":"
```

**Lösning:** Undvik kolon i SQL-strängar om möjligt. Använd secrets för autentisering och skicka bara `dbname` i ATTACH-strängen:
```java
// FEL — kolon i strängen:
"ATTACH 'ducklake:postgres:host=HOST port=PORT dbname=DB'"

// RÄTT — använd secret och bara dbname:
"ATTACH 'ducklake:postgres:dbname=ducklake' AS lake (...)"
```

---

### 7. Fel eclipse-temurin image-tagg

**Problemet:** Taggen `eclipse-temurin:21-jdk-slim` finns inte.

**Symtom:**
```
eclipse-temurin:21-jdk-slim: not found
```

**Lösning:** Använd `jammy` istället för `slim`:
```dockerfile
FROM eclipse-temurin:21-jdk-jammy AS build
FROM eclipse-temurin:21-jre-jammy
```

---

### 8. PostgreSQL persistent storage path

**Problemet:** Fel sökväg för persistent storage på PostgreSQL-containern.

**Rätt sökväg:** `/var/lib/postgresql/data` — detta är PostgreSQLs interna datakatalog och kan inte ändras.

---

### 9. MinIO kräver "server /data" som start-argument

**Problemet:** Om du glömmer att sätta `server /data` som Image start arguments startar MinIO i fel läge.

**Lösning:** Fyll alltid i **Image start arguments**: `server /data`

---

### 10. API_KEY i klartext i koden

**Problemet:** Om du hårdkodar `API_KEY` i koden och pushar till GitHub kan vem som helst läsa det.

**Lösning:** Använd alltid miljövariabel och en placeholder i koden:
```python
API_KEY = os.getenv("API_KEY", "change-me")
```
```properties
ducklake.api.key=${API_KEY:change-me}
```

Sätt det riktiga lösenordet som miljövariabel i KTH Cloud — aldrig i koden.

---

## Skapa egna API-endpoints

När infrastrukturen är på plats kan du skapa **vilka endpoints du vill** — det är bara SQL-frågor mot DuckLake bakom kulisserna.

### Hur det fungerar

1. **Definiera tabellen** i `init_db()` (Python) eller `openConnection()` (Java)
2. **Skapa endpoints** i `main.py` (Python) eller `ApiController.java` (Java)
3. **Skydda skrivoperationer** med API-nyckel

### Exempel — lägga till en ny tabell och endpoints

**Python — steg 1: skapa tabellen i database.py**
```python
def init_db():
    con = get_conn()
    con.execute("""
        CREATE TABLE IF NOT EXISTS lake.vader (
            datum DATE,
            stad VARCHAR,
            temperatur DOUBLE
        )
    """)
    con.close()
```

**Python — steg 2: skapa endpoints i main.py**
```python
class NyVader(BaseModel):
    datum: str
    stad: str
    temperatur: float

@app.get("/api/vader")
def get_vader():
    con = get_conn()
    rows = con.execute("SELECT datum, stad, temperatur FROM lake.vader ORDER BY datum").fetchall()
    con.close()
    return [{"datum": str(r[0]), "stad": r[1], "temperatur": r[2]} for r in rows]

@app.post("/api/vader", status_code=201, dependencies=[Depends(verify_key)])
def ny_vader(v: NyVader):
    con = get_conn()
    con.execute("INSERT INTO lake.vader VALUES (?, ?, ?)", [v.datum, v.stad, v.temperatur])
    con.close()
    return {"datum": v.datum, "stad": v.stad, "temperatur": v.temperatur}

@app.delete("/api/vader/{datum}", dependencies=[Depends(verify_key)])
def radera_vader(datum: str):
    con = get_conn()
    con.execute("DELETE FROM lake.vader WHERE datum = ?", [datum])
    con.close()
    return {"deleted": datum}
```

**Java — steg 1: skapa tabellen i DuckLakeService.java**
```java
stmt.execute("""
    CREATE TABLE IF NOT EXISTS lake.vader (
        datum DATE,
        stad VARCHAR,
        temperatur DOUBLE
    )""");
```

**Java — steg 2: skapa endpoints i ApiController.java**
```java
record NyVader(String datum, String stad, double temperatur) {}

@GetMapping("/api/vader")
public List<Map<String, Object>> getVader() throws Exception {
    return lake.query("SELECT datum, stad, temperatur FROM lake.vader ORDER BY datum");
}

@PostMapping("/api/vader")
public ResponseEntity<?> nyVader(@RequestHeader(value = "X-API-Key", required = false) String key,
                                  @RequestBody NyVader v) throws Exception {
    if (!validKey(key)) return unauthorized();
    lake.update("INSERT INTO lake.vader VALUES (?, ?, ?)", v.datum(), v.stad(), v.temperatur());
    return ResponseEntity.status(201).body(Map.of("datum", v.datum(), "stad", v.stad()));
}

@DeleteMapping("/api/vader/{datum}")
public ResponseEntity<?> raderaVader(@PathVariable String datum,
                                      @RequestHeader(value = "X-API-Key", required = false) String key) throws Exception {
    if (!validKey(key)) return unauthorized();
    lake.update("DELETE FROM lake.vader WHERE datum = ?", datum);
    return ResponseEntity.ok(Map.of("deleted", datum));
}
```

### Viktigt att tänka på

- **GET-endpoints** kan vara öppna för alla — ingen nyckel krävs
- **POST/DELETE-endpoints** bör skyddas med `X-API-Key`-headern
- **Tabellnamnet** i SQL måste matcha det du definierade i `init_db()` / `openConnection()`
- **DuckLake sparar all data automatiskt** som Parquet-filer — du behöver inte tänka på det

### Seed-data — förifylld data vid start

Om du vill att databasen ska innehålla exempeldata direkt, lägg till seed-logik som körs om tabellen är tom:

**Python:**
```python
_con = get_conn()
if _con.execute("SELECT COUNT(*) FROM lake.vader").fetchone()[0] == 0:
    _con.executemany("INSERT INTO lake.vader VALUES (?, ?, ?)", [
        ("2024-01-01", "Stockholm", -2.0),
        ("2024-07-01", "Göteborg",  22.5),
    ])
_con.close()
```

**Java:**
```java
ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM lake.vader");
rs.next();
if (rs.getInt(1) == 0) {
    stmt.execute("INSERT INTO lake.vader VALUES ('2024-01-01', 'Stockholm', -2.0)");
    stmt.execute("INSERT INTO lake.vader VALUES ('2024-07-01', 'Göteborg', 22.5)");
}
```

---

## Sammanfattning

| Steg | Teknologi | Port | Visibility |
|------|-----------|------|------------|
| 1. Katalog | PostgreSQL | 5432 | Private |
| 2. Lagring | MinIO | 9000 | Private |
| 3. API | FastAPI (Python) eller Spring Boot (Java) | 8000/8080 | Public |

**Fullständig källkod:** [github.com/WildRelation/ducklake-cloud](https://github.com/WildRelation/ducklake-cloud)
