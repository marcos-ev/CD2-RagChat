"""
Autenticação Google OAuth para RAG Data Platform.
Restringe domínio a @cd2.com.br (ou DOMAIN_ALLOWED).
BYPASS_AUTH=true desativa login e permite acesso livre.
"""

import os
from typing import List, Optional

from authlib.integrations.starlette_client import OAuth
from fastapi import Request, HTTPException, Depends
from starlette.config import Config

from database import get_db, get_user_by_email, create_or_update_user_from_google, get_or_create_bypass_user, User

BYPASS_AUTH = os.getenv("BYPASS_AUTH", "false").strip().lower() in ("true", "1", "yes")

# Domínio permitido (default: cd2.com.br)
DOMAIN_ALLOWED = os.getenv("DOMAIN_ALLOWED", "cd2.com.br").strip().lower()
if not DOMAIN_ALLOWED.startswith("@"):
    DOMAIN_ALLOWED = f"@{DOMAIN_ALLOWED}"


def _get_role_from_env(email: str) -> str:
    """
    Determina o role do usuário a partir de variáveis de ambiente.
    ADMIN_EMAILS=email1@cd2.com.br,email2@cd2.com.br
    PUBLICADOR_EMAILS=email1@cd2.com.br,email2@cd2.com.br
    """
    email = email.strip().lower()
    admin_emails = [e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]
    publicador_emails = [e.strip().lower() for e in os.environ.get("PUBLICADOR_EMAILS", "").split(",") if e.strip()]
    if email in admin_emails:
        return "admin"
    if email in publicador_emails:
        return "publicador"
    return "leitor"


def is_valid_domain(email: str) -> bool:
    """Verifica se o email termina com o domínio permitido."""
    if not email:
        return False
    email = email.strip().lower()
    # Domínio pode ser @cd2.com.br ou cd2.com.br
    domain = DOMAIN_ALLOWED if DOMAIN_ALLOWED.startswith("@") else f"@{DOMAIN_ALLOWED}"
    return email.endswith(domain)


# Configuração OAuth (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET via env)
config = Config(environ=os.environ)
oauth = OAuth(config)

oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


def get_current_user(request: Request, db=Depends(get_db)) -> User:
    """
    Dependency que obtém o usuário da sessão e valida no banco.
    Se BYPASS_AUTH=true, retorna usuário local sem exigir login.
    """
    if BYPASS_AUTH:
        return get_or_create_bypass_user(db)
    user_data = request.session.get("user")
    if not user_data:
        raise HTTPException(status_code=401, detail="Não autenticado. Faça login em /login")
    email = user_data.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Sessão inválida")
    user = get_user_by_email(db, email)
    if not user:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user


def require_role(required_roles: List[str]):
    """
    Dependency factory que verifica se current_user.role está em required_roles.
    Uso: current_user = Depends(require_role(["publicador", "admin"]))
    """
    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        role = (current_user.role or "leitor").strip().lower()
        if role not in [r.strip().lower() for r in required_roles]:
            raise HTTPException(
                status_code=403,
                detail=f"Acesso negado. Roles permitidos: {required_roles}"
            )
        return current_user
    return role_checker


def get_user_from_session(request: Request) -> Optional[dict]:
    """Retorna dados do usuário da sessão (sem validar no DB)."""
    return request.session.get("user")


def get_optional_user(request: Request, db=Depends(get_db)) -> Optional[User]:
    """
    Retorna o usuário da sessão ou None se ALLOW_ANONYMOUS_CHAT=true.
    Se BYPASS_AUTH=true, retorna usuário local (sempre logado).
    """
    if BYPASS_AUTH:
        return get_or_create_bypass_user(db)
    allow_anon = os.getenv("ALLOW_ANONYMOUS_CHAT", "false").strip().lower() in ("true", "1", "yes")
    user_data = request.session.get("user")
    if not user_data:
        if allow_anon:
            return None
        raise HTTPException(status_code=401, detail="Não autenticado. Faça login em /login")
    email = user_data.get("email")
    if not email:
        if allow_anon:
            return None
        raise HTTPException(status_code=401, detail="Sessão inválida")
    user = get_user_by_email(db, email)
    if not user and not allow_anon:
        raise HTTPException(status_code=401, detail="Usuário não encontrado")
    return user


def user_to_session_dict(user: User) -> dict:
    """Converte objeto User para dicionário armazenável na sessão."""
    return {
        "id": user.id,
        "email": user.email,
        "name": getattr(user, "name", "") or "",
        "role": user.role or "leitor",
    }
