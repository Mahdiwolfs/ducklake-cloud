package se.kth.ducklake.service;

import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.sql.*;
import java.util.*;

@Service
public class DuckLakeService {

    @Value("${ducklake.postgres.host}")     private String pgHost;
    @Value("${ducklake.postgres.port}")     private String pgPort;
    @Value("${ducklake.postgres.db}")       private String pgDb;
    @Value("${ducklake.postgres.user}")     private String pgUser;
    @Value("${ducklake.postgres.password}") private String pgPass;

    @Value("${ducklake.s3.endpoint}")  private String s3Endpoint;
    @Value("${ducklake.s3.keyid}")     private String s3KeyId;
    @Value("${ducklake.s3.secret}")    private String s3Secret;
    @Value("${ducklake.s3.bucket}")    private String s3Bucket;
    @Value("${ducklake.s3.region}")    private String s3Region;

    @PostConstruct
    public void installExtensions() throws SQLException {
        try (Connection conn = DriverManager.getConnection("jdbc:duckdb:");
             Statement stmt = conn.createStatement()) {
            stmt.execute("INSTALL ducklake");
            stmt.execute("INSTALL postgres");
            if (!s3Endpoint.isBlank()) {
                stmt.execute("INSTALL httpfs");
            }
        }
        seedIfEmpty();
    }

    public Connection openConnection() throws SQLException {
        Connection conn = DriverManager.getConnection("jdbc:duckdb:");
        try (Statement stmt = conn.createStatement()) {
            stmt.execute("LOAD ducklake");
            stmt.execute("LOAD postgres");

            stmt.execute("""
                CREATE OR REPLACE SECRET (
                    TYPE postgres,
                    HOST '%s',
                    PORT %s,
                    DATABASE '%s',
                    USER '%s',
                    PASSWORD '%s'
                )""".formatted(pgHost, pgPort, pgDb, pgUser, pgPass));

            String dataPath;
            if (!s3Endpoint.isBlank()) {
                stmt.execute("LOAD httpfs");
                stmt.execute("""
                    CREATE OR REPLACE SECRET (
                        TYPE s3,
                        KEY_ID '%s',
                        SECRET '%s',
                        REGION '%s',
                        ENDPOINT '%s',
                        URL_STYLE 'path',
                        USE_SSL false
                    )""".formatted(s3KeyId, s3Secret, s3Region, s3Endpoint));
                dataPath = "s3://" + s3Bucket + "/";
            } else {
                dataPath = "./data/lake/";
                new java.io.File(dataPath).mkdirs();
            }

            stmt.execute("ATTACH 'ducklake:postgres:dbname=" + pgDb + "' AS lake (DATA_PATH '" + dataPath + "')");

            stmt.execute("""
                CREATE TABLE IF NOT EXISTS lake.kunder (
                    id INTEGER, namn VARCHAR NOT NULL,
                    email VARCHAR NOT NULL, telefon VARCHAR
                )""");
            stmt.execute("""
                CREATE TABLE IF NOT EXISTS lake.produkter (
                    id INTEGER, namn VARCHAR NOT NULL,
                    pris DOUBLE NOT NULL, lagersaldo INTEGER DEFAULT 0
                )""");
            stmt.execute("""
                CREATE TABLE IF NOT EXISTS lake.ordrar (
                    id INTEGER, kund_id INTEGER, produkt_id INTEGER,
                    antal INTEGER NOT NULL,
                    skapad TIMESTAMP DEFAULT current_timestamp
                )""");
        }
        return conn;
    }

    private void seedIfEmpty() throws SQLException {
        try (Connection conn = openConnection();
             Statement stmt = conn.createStatement()) {
            ResultSet rs = stmt.executeQuery("SELECT COUNT(*) FROM lake.kunder");
            rs.next();
            if (rs.getInt(1) == 0) {
                stmt.execute("""
                    INSERT INTO lake.kunder VALUES
                    (1,'Anna Svensson','anna@example.com','070-1234567'),
                    (2,'Erik Johansson','erik@example.com','073-9876543'),
                    (3,'Maria Lindqvist','maria@example.com','076-5551234')
                    """);
                stmt.execute("""
                    INSERT INTO lake.produkter VALUES
                    (1,'Laptop',9999.0,15),
                    (2,'Hörlurar',799.0,50),
                    (3,'Tangentbord',1299.0,30)
                    """);
                stmt.execute("""
                    INSERT INTO lake.ordrar (id,kund_id,produkt_id,antal) VALUES
                    (1,1,1,1),(2,1,2,2),(3,2,3,1)
                    """);
            }
        }
    }

    public List<Map<String, Object>> query(String sql, Object... params) throws SQLException {
        try (Connection conn = openConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            for (int i = 0; i < params.length; i++) ps.setObject(i + 1, params[i]);
            ResultSet rs = ps.executeQuery();
            ResultSetMetaData meta = rs.getMetaData();
            List<Map<String, Object>> rows = new ArrayList<>();
            while (rs.next()) {
                Map<String, Object> row = new LinkedHashMap<>();
                for (int i = 1; i <= meta.getColumnCount(); i++)
                    row.put(meta.getColumnLabel(i), rs.getObject(i));
                rows.add(row);
            }
            return rows;
        }
    }

    public void update(String sql, Object... params) throws SQLException {
        try (Connection conn = openConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            for (int i = 0; i < params.length; i++) ps.setObject(i + 1, params[i]);
            ps.executeUpdate();
        }
    }

    public Object scalar(String sql, Object... params) throws SQLException {
        try (Connection conn = openConnection();
             PreparedStatement ps = conn.prepareStatement(sql)) {
            for (int i = 0; i < params.length; i++) ps.setObject(i + 1, params[i]);
            ResultSet rs = ps.executeQuery();
            return rs.next() ? rs.getObject(1) : null;
        }
    }
}
