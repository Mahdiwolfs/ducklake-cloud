# Titanic ML — DuckLake som Feature Store

> **Extra exempel** — ingår inte i huvudprojektet. Visar hur DuckLake kan användas som feature store för machine learning.

## Vad detta visar

```
Titanic CSV (URL)
      ↓
lake.raw_titanic     ← rådata, orörd, versionerad
      ↓ SQL feature engineering
lake.features        ← rensad + enkodad, versionerad
      ↓ scikit-learn RandomForest
lake.predictions     ← prediktioner sparade, versionerade
```

Varje steg skapar en ny **snapshot** i DuckLake — du kan alltid gå tillbaka och se hur datan såg ut i varje steg.

---

## Endpoints

| Endpoint | Beskrivning |
|----------|-------------|
| `GET /accuracy` | Modellens träffsäkerhet + rapport |
| `GET /features` | Features-tabellen (efter engineering) |
| `GET /predictions` | Prediktioner för alla passagerare |
| `GET /snapshots` | DuckLake time travel — alla versioner |
| `POST /predict` | Predicera överlevnad för en ny passagerare |

### Exempel — predicera överlevnad

```bash
curl -X POST https://<deployment>.app.cloud.cbh.kth.se/predict \
  -H "Content-Type: application/json" \
  -d '{
    "passenger_class": 1,
    "is_male": 0,
    "age": 29,
    "family_size": 0,
    "fare": 100.0,
    "embarked_enc": 1
  }'
```

Svar:
```json
{
  "predicted_survival": 1,
  "survival_probability": 0.87,
  "tolkning": "Överlevde"
}
```

---

## Deploya på KTH Cloud

- **Image:** `ghcr.io/wildrelation/ducklake-cloud/ml-example:latest`
- **Port:** `8000`
- **Visibility:** Public
- **Persistent storage:** App path `/app` (för att spara DuckLake-filerna)

Inga extra miljövariabler krävs — appen laddar Titanic-data direkt från GitHub vid start.
