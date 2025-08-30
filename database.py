import os
from dotenv import load_dotenv
from sqlalchemy import (create_engine, Column, Integer, String, Float, 
                        DateTime, func, VARCHAR)
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

# Load environment variables from a .env file
load_dotenv()

# Retrieve database credentials from environment variables, with defaults
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "g273f123")
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = os.getenv("MYSQL_PORT", "3306")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "binance")

# Create the connection URL for SQLAlchemy
DATABASE_URL = f"mysql+mysqlconnector://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}"

# --- Database Setup ---
try:
    # The engine is the entry point to the database
    engine = create_engine(DATABASE_URL, pool_recycle=3600, echo=False)
    
    # SessionLocal is a factory for creating new database sessions
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Base is a class that all model classes will inherit from
    Base = declarative_base()
    print("✅ Database connection established successfully.")
except Exception as e:
    print(f"❌ Error connecting to the database: {e}")
    engine = None
    SessionLocal = None
    Base = object # Fallback to prevent crashes on import

# --- Trades Table Model ---
# This class defines the structure of the 'trades' table.
class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(VARCHAR(20), nullable=False, index=True)
    side = Column(VARCHAR(10), nullable=False)
    quantity = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float)
    pnl = Column(Float, nullable=False, default=0.0, index=True)
    roe = Column(Float, nullable=True)
    leverage = Column(Integer, nullable=False)
    close_type = Column(VARCHAR(20), nullable=True)
    timestamp = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    date = Column(VARCHAR(10), nullable=False, index=True)
    duration = Column(Float, nullable=True) # Duration in seconds

# --- Daily Summary Table Model ---
# This class defines the structure of the 'daily_summary' table.
class DailySummary(Base):
    __tablename__ = "daily_summary"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(VARCHAR(10), nullable=False, unique=True, index=True)
    total_trades = Column(Integer, default=0)
    daily_pnl = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

# --- Performance Metrics Table Model ---
class PerformanceMetrics(Base):
    __tablename__ = "performance_metrics"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    symbol = Column(VARCHAR(20), nullable=False, index=True)
    win_rate = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    avg_win = Column(Float, default=0.0)
    avg_loss = Column(Float, default=0.0)
    recommended_leverage = Column(Integer, default=20)
    strategy_effectiveness = Column(Float, default=0.0)
    market_volatility = Column(Float, default=0.0)

# --- Initialization Function ---
def init_db():
    """
    Creates the database tables if they do not already exist.
    """
    if engine:
        try:
            Base.metadata.create_all(bind=engine)
            print("🔍 Database tables verified/created.")
        except Exception as e:
            print(f"❌ Could not create tables: {e}")