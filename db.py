"""
Shared database connection for the POC.
Every script imports get_engine() from here, so the connection
details live in one place.

Connection details come from .env (never committed):
  DB_SERVER    server name or IP, e.g. 10.0.0.244 or 10.0.0.244,1433
  DB_NAME      database name, e.g. EPM
  DB_USER      SQL login; leave empty to use your Windows login
  DB_PASSWORD  password for DB_USER
  DB_SCHEMA    the schema we work in, e.g. dbo, or "all"
"""
import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DB_SERVER = os.getenv("DB_SERVER", "")
DB_NAME = os.getenv("DB_NAME", "")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_SCHEMA = os.getenv("DB_SCHEMA", "")


def get_engine():
    if DB_USER:
        auth = f"UID={DB_USER};PWD={DB_PASSWORD}"
    else:
        auth = "Trusted_Connection=yes"
    odbc = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={DB_SERVER};DATABASE={DB_NAME};{auth};"
        "TrustServerCertificate=yes;ApplicationIntent=ReadOnly"
    )
    return create_engine(f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}")
