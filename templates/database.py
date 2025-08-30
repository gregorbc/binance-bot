try:
    # The engine is the entry point to the database
    engine = create_engine(DATABASE_URL, pool_recycle=3600)
    
    # SessionLocal is a factory for creating new database sessions
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
    # Base is a class that all model classes will inherit from
    Base = declarative_base()
    print("✅ Database connection established successfully.")
except Exception as e:
    print(f"❌ Error connecting to the database: {e}")
    # Add retry logic here
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            print(f"Retrying database connection (attempt {retry_count + 1}/{max_retries})...")
            time.sleep(2 * (retry_count + 1))  # Exponential backoff
            engine = create_engine(DATABASE_URL, pool_recycle=3600)
            SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
            Base = declarative_base()
            print("✅ Database connection established successfully on retry.")
            break
        except Exception as retry_e:
            print(f"❌ Retry failed: {retry_e}")
            retry_count += 1
    
    if retry_count >= max_retries:
        print("❌ All database connection retries failed. Starting without database support.")
        engine = None
        SessionLocal = None
        Base = object  # Fallback to prevent crashes on import