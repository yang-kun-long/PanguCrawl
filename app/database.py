from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.config import settings

# 创建同步引擎 (为了简单起见，CRUD操作暂用同步模式，爬虫逻辑里用异步)
engine = create_engine(settings.DATABASE_URL)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()