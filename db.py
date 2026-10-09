"""
Shared database connection for the POC.
Every script imports get_engine() from here, so the connection
details live in one place.
"""
from sqlalchemy import create_engine

DB_NAME = "AdventureWorks2025"

def get_engine():
    conn_str = (
        f"mssql+pyodbc://@localhost/{DB_NAME}"
        "?driver=ODBC+Driver+18+for+SQL+Server"
        "&trusted_connection=yes&TrustServerCertificate=yes"
    )
    return create_engine(conn_str)
