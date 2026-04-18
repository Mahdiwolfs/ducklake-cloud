FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python3 -c "import duckdb; con = duckdb.connect(); \
    con.execute('INSTALL ducklake'); \
    con.execute('INSTALL httpfs')"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
