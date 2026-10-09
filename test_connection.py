import pandas as pd
from sqlalchemy import create_engine

conn_str = (
    "mssql+pyodbc://@localhost/AdventureWorks2025"
    "?driver=ODBC+Driver+18+for+SQL+Server"
    "&trusted_connection=yes&TrustServerCertificate=yes"
)
engine = create_engine(conn_str)

df = pd.read_sql("""
    SELECT TABLE_SCHEMA, COUNT(*) AS table_count
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_TYPE = 'BASE TABLE'
    GROUP BY TABLE_SCHEMA
""", engine)
print(df)