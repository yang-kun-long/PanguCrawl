from app.database import engine
from app.models import Base

def init_db():
    print("正在创建数据库表...")
    # SQLAlchmey 会根据 models.py 定义的结构生成 CREATE TABLE 语句
    Base.metadata.create_all(bind=engine)
    print("数据库表创建成功！")

if __name__ == "__main__":
    init_db()