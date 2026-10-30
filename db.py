"""
The database connection, in one place.

Every script gets its connection from here, so the server, database and
login are set once, in the .env file (never in code, never in git):

  DB_SERVER    server address, e.g. 10.0.0.244
  DB_NAME      database name, e.g. EPM_For_Automation
  DB_USER      SQL Server login
  DB_PASSWORD  its password

The login only has read rights, and the scripts only run SELECT queries.
"""
import os
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv()

DB_SERVER = os.getenv("DB_SERVER", "")
DB_NAME = os.getenv("DB_NAME", "")
DB_USER = os.getenv("DB_USER", "")


def get_engine():
    """A SQLAlchemy engine for the database named in .env."""
    odbc = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={DB_SERVER};DATABASE={DB_NAME};"
        f"UID={DB_USER};PWD={os.getenv('DB_PASSWORD', '')};"
        "TrustServerCertificate=yes;"
    )
    return create_engine(f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}")
