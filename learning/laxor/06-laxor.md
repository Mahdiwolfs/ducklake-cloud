# Läxor — Modul 06: Access-nycklar

## Uppgift 1 — Begär en read-only nyckel
1. Starta systemet lokalt med `docker compose up --build`
2. Gå till `http://localhost:8000`
3. Skapa en read-only nyckel för användaren `test-student`
4. Kopiera DuckDB-scriptet och anslut till lake:en
5. Kör: `SHOW TABLES FROM lake;` — vilka tabeller ser du?

---

## Uppgift 2 — Testa behörighetsgränser
1. Anslut med en **read-only** nyckel
2. Försök köra: `INSERT INTO lake.kunder VALUES (99, 'Test', 'test@test.com', NULL)`
3. Vad händer? Varför?

---

## Uppgift 3 — Python-anslutning
Skriv ett Python-script som:
1. Begär en read-only nyckel via API:et (med `requests`-biblioteket)
2. Parsar svaret och extraherar scriptet
3. Ansluter till lake:en med DuckDB
4. Skriver ut alla dataset som en pandas DataFrame

---

## Uppgift 4 — Återkalla en nyckel
1. Skapa en nyckel för `temp-user`
2. Verifiera att du kan ansluta med den
3. Återkalla nyckeln via webbfrontenden
4. Försök ansluta igen — vad händer?

---

## Diskussionsfrågor
- Varför behövs **två** nycklar (S3 + PostgreSQL) och inte bara en?
- Vad är skillnaden mellan att ha API-nyckel och access-nyckel i det här systemet?
- Varför är MinIO deprecated och vad är Garage?
