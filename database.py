import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

# Carga variables de entorno
load_dotenv()

MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "g273f123")
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "binance")

# CORRECCIÓN: Usar MYSQL_DATABASE en lugar de MYSQL_DB
DATABASE_URL = f"mysql+mysqlconnector://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

engine = create_engine(DATABASE_URL, pool_recycle=3600)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Trade(Base):
    __tablename__ = "trades"
    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), nullable=False, index=True)
    side = Column(String(10), nullable=False)
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=False)
    pnl = Column(Float, nullable=False, default=0.0)
    roe = Column(Float, nullable=False, default=0.0)
    leverage = Column(Integer, nullable=False)
    close_type = Column(String(20), nullable=False, default="unknown")
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    date = Column(String(10), nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    strategy = Column(String(50), nullable=True)
    duration = Column(Float, nullable=True)

class PerformanceMetrics(Base):
    __tablename__ = "performance_metrics"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(String(20), nullable=False)
    # CORRECCIÓN: Añadir coma faltante después de Float
    win_rate = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    avg_win = Column(Float, default=0.0)
    avg_loss = Column(Float, default=0.0)
    recommended_leverage = Column(Integer, default=20)
    strategy_effectiveness = Column(Float, default=0.0)
    market_volatility = Column(Float, default=0.0)

def init_db():
    """Crea las tablas si no existen."""
    Base.metadata.create_all(bind=engine)