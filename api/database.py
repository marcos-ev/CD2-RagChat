"""
Configuração do banco de dados PostgreSQL com SQLAlchemy
"""

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, JSON, ForeignKey, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime
from typing import Optional

# Configurações do banco
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_USER = os.getenv("POSTGRES_USER", "raguser")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "ragpass")
POSTGRES_DB = os.getenv("POSTGRES_DB", "ragdb")

# URL de conexão
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Criar engine
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# Criar session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para modelos
Base = declarative_base()


# Modelo de Usuário (OAuth Google)
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True)
    name = Column(String(255), default="")
    role = Column(String(50), default="leitor")  # leitor | publicador | admin
    created_at = Column(DateTime, default=datetime.utcnow)


# Modelo de Documento
class Document(Base):
    __tablename__ = "documents"
    
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    content = Column(Text)
    # Mapeamos embedding como TEXT apenas para leitura (o tipo real no Postgres é vector)
    # Isso evita problemas de adaptação de tipos com BYTEA e a extensão pgvector.
    embedding = Column(Text)
    # 'metadata' é um nome reservado na API declarativa do SQLAlchemy (Base.metadata)
    # Por isso, usamos o nome de atributo 'extra_metadata', mas mantemos o nome da coluna como 'metadata'
    extra_metadata = Column("metadata", JSON)
    chunk_index = Column(Integer, default=0)
    parent_doc_id = Column(Integer, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Modelo de Conversa
class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title = Column(String(500), default="Nova conversa")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


# Modelo de Mensagem
class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(20), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    sources = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)


# Log de auditoria (uploads, exclusões)
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    action = Column(String(50), nullable=False)  # upload, delete, etc.
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    details = Column(JSON)  # {filename, document_id, ...}
    created_at = Column(DateTime, default=datetime.utcnow)


# Configurações da aplicação (instruções do assistente, etc.)
class AppSetting(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), nullable=False, unique=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def get_db():
    """Dependency para obter sessão do banco"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_user_by_email(db, email: str) -> Optional[User]:
    """Retorna usuário por email."""
    return db.query(User).filter(User.email == email.strip().lower()).first()


BYPASS_USER_EMAIL = "bypass@local"


def get_or_create_bypass_user(db) -> User:
    """Cria ou retorna usuário para modo sem login (BYPASS_AUTH=true)."""
    user = db.query(User).filter(User.email == BYPASS_USER_EMAIL).first()
    if user:
        return user
    user = User(email=BYPASS_USER_EMAIL, name="Usuário local", role="admin")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_or_update_user_from_google(db, email: str, name: str = "", role: str = "leitor") -> User:
    """
    Cria ou retorna usuário existente a partir de login Google.
    Se o usuário não existir, cria com o role determinado por ADMIN_EMAILS/PUBLICADOR_EMAILS.
    """
    email = email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user:
        if name and not user.name:
            user.name = name
            db.commit()
        return user
    user = User(email=email, name=(name or "").strip(), role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_app_setting(db, key: str, default: str = "") -> str:
    """Retorna valor de app_settings por key."""
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return (row.value or default) if row else default


def set_app_setting(db, key: str, value: str) -> None:
    """Define valor de app_settings."""
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.commit()


def init_db():
    """Inicializar banco de dados (criar tabelas se não existirem) e rodar migrações."""
    try:
        Base.metadata.create_all(bind=engine)
        # Seed app_settings se vazio
        try:
            db = SessionLocal()
            if db.query(AppSetting).filter(AppSetting.key == "rag_instructions").first() is None:
                db.add(AppSetting(key="rag_instructions", value=""))
                db.commit()
            db.close()
        except Exception:
            pass
        # Migração: sort_order em conversations (para instalações existentes)
        try:
            with engine.connect() as conn:
                r = conn.execute(text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'conversations' AND column_name = 'sort_order'"
                ))
                if r.fetchone() is None:
                    conn.execute(text("ALTER TABLE conversations ADD COLUMN sort_order INT DEFAULT 0"))
                    conn.execute(text("UPDATE conversations SET sort_order = id"))
                conn.commit()
        except Exception:
            pass  # Coluna pode já existir
        print("Banco de dados inicializado com sucesso")
    except Exception as e:
        print(f"Erro ao inicializar banco de dados: {e}")

