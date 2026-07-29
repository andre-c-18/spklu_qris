import os
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Load file .env
load_dotenv()

# Ambil data dari env
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "3306")
DB_NAME = os.getenv("DB_NAME")

# Bentuk string koneksi MySQL (kita gunakan pymysql sebagai driver)
SQLALCHEMY_DATABASE_URL = f"mysql+pymysql://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

# Setup Engine SQLAlchemy
engine = create_engine(SQLALCHEMY_DATABASE_URL)

# Setup Session
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Setup Base Model untuk definisi tabel nanti
Base = declarative_base()

# Dependency get_db untuk digunakan di routers
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()