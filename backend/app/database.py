import pyodbc
import pandas as pd
from contextlib import contextmanager
from app.config import settings
import warnings
warnings.filterwarnings('ignore', category=UserWarning, module='pandas')

def get_db_connection():
    """Establishes a connection to Microsoft Fabric Data Warehouse using a Service Principal."""
    conn_str = (
        f"DRIVER={settings.DB_DRIVER};"
        f"SERVER={settings.FABRIC_SERVER};"
        f"DATABASE={settings.FABRIC_DATABASE};"
        f"UID={settings.CLIENT_ID};"
        f"PWD={settings.CLIENT_SECRET};"
        "Authentication=ActiveDirectoryServicePrincipal;"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
    )
    return pyodbc.connect(conn_str)

@contextmanager
def get_cursor():
    """Context manager for non-SELECT operations (UPDATE, INSERT)."""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        yield cursor
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()

def execute_query(query: str, params: tuple = ()) -> pd.DataFrame:
    """Executes SELECT queries and returns results as a pandas DataFrame."""
    conn = get_db_connection()
    try:
        return pd.read_sql(query, conn, params=params)
    finally:
        conn.close()

def execute_non_query(query: str, params: tuple = ()):
    """Executes INSERT, UPDATE, or DELETE operations in Microsoft Fabric."""
    with get_cursor() as cursor:
        cursor.execute(query, params)

def execute_non_query_utf8_safe(query: str, json_string: str):
    """Executes OPENJSON operations in Microsoft Fabric while forcing 
    pyodbc to bind the parameter strictly as SQL_WVARCHAR to prevent UTF-8/LOB collation errors.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.setinputsizes([(pyodbc.SQL_WVARCHAR, 0, 0)])
        cursor.execute(query, (json_string,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()
        conn.close()