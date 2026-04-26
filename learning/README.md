# Studiehandledning — DuckLake på KTH Cloud

Denna guide är skapad för att hjälpa dig och din grupp förstå allt ni byggde. Gå igenom modulerna i ordning — varje modul bygger på den förra.

---

## Lärandemål

När du är klar med denna guide ska du kunna:

- ✅ Förklara vad Docker är och varför man använder det
- ✅ Förklara vad ett REST API är och hur GET/POST/DELETE fungerar
- ✅ Förklara vad DuckLake är och varför det skiljer sig från PostgreSQL
- ✅ Förklara varför man behöver tre separata deployments
- ✅ Förklara hur Python och Java ansluter till DuckLake på olika sätt
- ✅ Identifiera och förstå de vanligaste fällorna vid deployment
- ✅ Begära och använda access-nycklar för att ansluta till en central lake
- ✅ Förklara skillnaden mellan read-only och read/write behörighet

---

## Moduler

| Modul | Ämne | Tid |
|-------|------|-----|
| [01 — Grundbegrepp](01-grundbegrepp.md) | Docker, API, REST, containers | ~30 min |
| [02 — DuckLake](02-ducklake.md) | Parquet, katalog, PostgreSQL, MinIO | ~30 min |
| [03 — Deployment](03-deployment.md) | KTH Cloud, Kubernetes, miljövariabler | ~20 min |
| [04 — Python API](04-python-api.md) | FastAPI, DuckDB, anslutning | ~20 min |
| [05 — Java API](05-java-api.md) | Spring Boot, JDBC, skillnader mot Python | ~20 min |
| [06 — Access-nycklar](06-access-nycklar.md) | Behörigheter, nyckelgenerering, MinIO/Garage | ~30 min |
| [Lokal setup](lokal-setup.md) | Bygg hela systemet från grunden lokalt | ~60 min |
| [Läxor](laxor/) | Övningar per modul | ~2 timmar |

---

## Hur du använder denna guide

1. Läs igenom modulen
2. Gör läxorna till modulen innan du går vidare
3. Diskutera svaren med din grupp

---

## Källkod och live-exempel

- Repo: [github.com/Mahdiwolfs/ducklake-cloud](https://github.com/Mahdiwolfs/ducklake-cloud)
- Fullständig guide: [GUIDE.md](../GUIDE.md)
