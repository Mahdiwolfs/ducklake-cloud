import duckdb
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

TITANIC_URL = "https://raw.githubusercontent.com/datasciencedojo/datasets/master/titanic.csv"


def build(con: duckdb.DuckDBPyConnection):
    """Kör hela pipeline:n: rådata → features → träning → prediktioner."""

    # ── Steg 1: Ladda rådata ──────────────────────────────────────────────────
    con.execute(f"""
        CREATE TABLE IF NOT EXISTS lake.raw_titanic AS
        SELECT * FROM read_csv_auto('{TITANIC_URL}')
    """)

    # ── Steg 2: Feature engineering ───────────────────────────────────────────
    con.execute("""
        CREATE TABLE IF NOT EXISTS lake.features AS
        SELECT
            PassengerId,
            Survived                              AS label,
            Pclass                                AS passenger_class,
            CASE Sex WHEN 'male' THEN 1 ELSE 0 END AS is_male,
            COALESCE(Age, 29.7)                   AS age,
            SibSp + Parch                         AS family_size,
            Fare                                  AS fare,
            CASE WHEN Embarked = 'S' THEN 0
                 WHEN Embarked = 'C' THEN 1
                 WHEN Embarked = 'Q' THEN 2
                 ELSE 0 END                       AS embarked_enc
        FROM lake.raw_titanic
        WHERE Fare IS NOT NULL
    """)

    # ── Steg 3: Träna modell ──────────────────────────────────────────────────
    df = con.execute("""
        SELECT passenger_class, is_male, age, family_size, fare, embarked_enc, label
        FROM lake.features
    """).df()

    feature_cols = ["passenger_class", "is_male", "age", "family_size", "fare", "embarked_enc"]
    X = df[feature_cols]
    y = df["label"]

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    model = RandomForestClassifier(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    accuracy = accuracy_score(y_test, model.predict(X_test))
    report   = classification_report(y_test, model.predict(X_test), output_dict=True)

    # ── Steg 4: Spara prediktioner i laken ───────────────────────────────────
    df_all = con.execute("""
        SELECT PassengerId, passenger_class, is_male, age, family_size, fare, embarked_enc
        FROM lake.features
    """).df()

    X_all = df_all[feature_cols]
    df_all["predicted_survival"]    = model.predict(X_all)
    df_all["survival_probability"]  = model.predict_proba(X_all)[:, 1].round(4)

    con.register("predictions_df", df_all[["PassengerId", "predicted_survival", "survival_probability"]])
    con.execute("""
        CREATE TABLE IF NOT EXISTS lake.predictions AS
        SELECT * FROM predictions_df
    """)

    return model, feature_cols, accuracy, report

