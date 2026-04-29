import sys
import os
from sqlalchemy import create_engine, inspect
# Добавляем путь к db в sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../db')))
from sqlalchemy.orm import sessionmaker
from db.base import DATABASE_URL

def check_clients_table():
    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)

    columns = inspector.get_columns('clients')
    column_names = [column['name'] for column in columns]
    
    return column_names

if __name__ == "__main__":
    column_names = check_clients_table()
    print("Columns in 'clients' table:", column_names)