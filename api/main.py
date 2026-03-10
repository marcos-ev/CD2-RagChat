"""
FastAPI - API principal para RAG Data Platform
Fornece endpoints para upload, busca semântica e RAG
Autenticação: Google OAuth com restrição de domínio @cd2.com.br
"""

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Request, Header
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import asyncio
import time
import re
import unicodedata
import math
from contextlib import asynccontextmanager
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware

from database import get_db, init_db, get_app_setting, set_app_setting
from embeddings_service import EmbeddingsService
from rag_service import RAGService
from document_service import DocumentService
from qdrant_service import QdrantService
from auth import oauth, is_valid_domain, get_current_user, get_optional_user, require_role, user_to_session_dict, _get_role_from_env, BYPASS_AUTH
from database import User, Conversation, Message, Document, AuditLog, create_or_update_user_from_google
from sqlalchemy import text

# Configurações
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-me-in-production-use-long-random-string")
INGEST_API_KEY = os.getenv("INGEST_API_KEY", "").strip()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialização e limpeza da aplicação"""
    # Inicializar banco de dados
    init_db()
    
    # Inicializar serviços
    app.state.embeddings_service = EmbeddingsService()
    app.state.qdrant_service = QdrantService()
    await app.state.qdrant_service.ensure_collection()
    app.state.rag_service = RAGService()
    app.state.document_service = DocumentService()
    
    yield
    
    # Cleanup (se necessário)
    pass


# Caminho base da API
BASE_DIR = Path(__file__).resolve().parent


# Rate limiting
limiter = Limiter(key_func=get_remote_address)

# Criar aplicação FastAPI
app = FastAPI(
    title="RAG Data Platform API",
    description="API para upload, busca semântica e RAG com documentos",
    version="1.0.0",
    lifespan=lifespan
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Session/cookie para manter usuário logado (OAuth)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, same_site="lax")

# Modelos Pydantic
class SearchRequest(BaseModel):
    query: str
    limit: int = 5
    threshold: float = 0.7


class SearchResult(BaseModel):
    id: int
    filename: str
    content: str
    similarity: float
    metadata: Optional[dict] = None


class RAGRequest(BaseModel):
    query: str
    limit: int = 3
    temperature: float = 0.7


class RAGResponse(BaseModel):
    answer: str
    sources: List[SearchResult]
    query: str


class OpenAIChatMessage(BaseModel):
    role: str
    content: str


class OpenAIChatCompletionRequest(BaseModel):
    model: Optional[str] = None
    messages: List[OpenAIChatMessage]
    temperature: float = 0.4
    max_tokens: int = 4096
    stream: bool = False


def _strip_accents(text: str) -> str:
    """Normaliza texto removendo acentos para busca textual mais robusta."""
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c))


def _build_query_terms(query: str, max_terms: int = 8) -> List[str]:
    """Extrai termos relevantes para fallback textual (sem acentos)."""
    stopwords = {
        "como", "qual", "quais", "que", "pra", "para", "com", "sem", "sobre",
        "de", "da", "do", "das", "dos", "na", "no", "nas", "nos", "e", "ou",
        "um", "uma", "valor", "troca", "trocar", "altera", "alterar", "mudar",
    }
    normalized_query = _strip_accents((query or "").lower())
    raw_terms = [t for t in re.split(r"\W+", normalized_query) if len(t) >= 3]
    terms = []
    for term in raw_terms:
        if term in stopwords:
            continue
        if term not in terms:
            terms.append(term)
        if len(terms) >= max_terms:
            break
    if not terms and normalized_query.strip():
        terms = [normalized_query.strip()]
    return terms


def _safe_similarity(value) -> float:
    """Garante valor de similaridade serializável e finito."""
    try:
        parsed = float(value)
    except Exception:
        return 0.0
    if not math.isfinite(parsed):
        return 0.0
    return parsed


def _lexical_score(filename: str, content: str, terms: List[str]) -> int:
    """Pontuação lexical simples (case/accent-insensitive) para reranqueamento."""
    if not terms:
        return 0
    haystack = _strip_accents(f"{filename or ''} {content or ''}".lower())
    score = 0
    for term in terms:
        score += haystack.count(term)
    return score


def _contains_strong_term(filename: str, content: str, terms: List[str]) -> bool:
    """Identifica se a linha contém ao menos um termo específico (>= 8 chars)."""
    strong_terms = [t for t in terms if len(t) >= 8]
    if not strong_terms:
        return False
    haystack = _strip_accents(f"{filename or ''} {content or ''}".lower())
    return any(t in haystack for t in strong_terms)


def _redact_secrets(text: str) -> str:
    """Redige credenciais comuns antes de enviar contexto/fontes ao usuário."""
    if not text:
        return ""
    redacted = text
    patterns = [
        r"(?im)(x-api-key\s*[:=]\s*)([^\s\r\n,;]+)",
        r"(?im)(password\s*[:=]\s*)([^\s\r\n,;]+)",
        r"(?im)(username\s*[:=]\s*)([^\s\r\n,;]+)",
        r"(?im)(authorization\s*[:=]\s*bearer\s+)([^\s\r\n,;]+)",
    ]
    for pattern in patterns:
        redacted = re.sub(pattern, r"\1[REDACTED]", redacted)
    return redacted


async def _semantic_search_documents(
    db,
    embeddings_service: EmbeddingsService,
    qdrant_service: QdrantService,
    query: str,
    limit: int,
    threshold: float = 0.0,
):
    query_embedding = await asyncio.to_thread(embeddings_service.generate_embedding, query)
    hits = await qdrant_service.search(
        query_vector=query_embedding.tolist(),
        limit=limit,
        score_threshold=threshold,
    )
    if not hits:
        return []
    ids = [hit.get("id") for hit in hits if hit.get("id") is not None]
    if not ids:
        return []
    docs = db.query(Document).filter(Document.id.in_(ids)).all()
    docs_by_id = {doc.id: doc for doc in docs}
    ordered = []
    for hit in hits:
        doc_id = hit.get("id")
        doc = docs_by_id.get(doc_id)
        if not doc:
            continue
        ordered.append((doc, float(hit.get("score", 0.0))))
    return ordered


# Modelos para Chat e Conversas
class ChatRequest(BaseModel):
    query: str
    conversation_id: Optional[int] = None


class ChatResponse(BaseModel):
    answer: str
    sources: List[SearchResult]
    conversation_id: int
    message_id: int
    title: Optional[str] = None


class ConversationCreateResponse(BaseModel):
    id: int
    title: str
    created_at: Optional[str] = None


class ConversationListItem(BaseModel):
    id: int
    title: str
    created_at: Optional[str] = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: Optional[str] = None
    sources: Optional[List[dict]] = None


class ConversationDetail(BaseModel):
    id: int
    title: str
    created_at: Optional[str] = None
    messages: List[MessageOut]


class ConversationUpdateRequest(BaseModel):
    title: Optional[str] = None


class ConversationReorderRequest(BaseModel):
    order: List[int]


# --- Rotas públicas (sem auth): /, /health, /login, /auth/callback, /logout ---

# Endpoints
ALLOW_ANONYMOUS = os.getenv("ALLOW_ANONYMOUS_CHAT", "false").strip().lower() in ("true", "1", "yes")


@app.get("/")
async def root():
    """Endpoint raiz"""
    return {
        "message": "RAG Data Platform API",
        "version": "1.0.0",
        "allow_anonymous_chat": ALLOW_ANONYMOUS,
        "bypass_auth": BYPASS_AUTH,
        "endpoints": {
            "login": "/login",
            "logout": "/logout",
            "me": "/me",
            "upload": "/upload",
            "search": "/search",
            "rag": "/rag",
            "chat": "/chat",
            "ingest_upload": "/ingest/upload",
            "openai_models": "/v1/models",
            "openai_chat_completions": "/v1/chat/completions",
            "conversations": "/conversations",
            "documents": "/documents",
            "admin_users": "/admin/users",
            "health": "/health"
        }
    }


@app.get("/login")
async def login(request: Request):
    """Redireciona para Google OAuth. Público."""
    # Usar APP_URL para evitar redirect_uri_mismatch (adicione exatamente esta URL no Google Cloud Console)
    app_url = os.getenv("APP_URL", "").strip().rstrip("/")
    if app_url:
        redirect_uri = f"{app_url}/auth/callback"
    else:
        redirect_uri = str(request.url_for("auth_callback"))
    return await oauth.google.authorize_redirect(request, redirect_uri)


@app.get("/auth/callback")
async def auth_callback(request: Request, db=Depends(get_db)):
    """Callback OAuth Google. Valida domínio, cria/atualiza usuário, seta sessão. Público."""
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Erro no callback OAuth: {e}")
    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    name = (userinfo.get("name") or "").strip()
    if not email:
        raise HTTPException(status_code=400, detail="Email não obtido do Google")
    if not is_valid_domain(email):
        raise HTTPException(status_code=403, detail="Acesso restrito ao domínio permitido")
    role = _get_role_from_env(email)
    user = create_or_update_user_from_google(db, email, name, role)
    request.session["user"] = user_to_session_dict(user)
    return RedirectResponse(url="/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    """Limpa sessão. Público (idempotente se já deslogado)."""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    """Retorna usuário logado (exige auth)."""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.name or "",
        "role": current_user.role or "leitor",
    }


def _is_internal_request(request: Request) -> bool:
    """Verifica se a requisição vem da rede interna (ingestion ou localhost)."""
    client = request.client
    if not client or not client.host:
        return False
    host = client.host
    if host in ("127.0.0.1", "localhost", "::1"):
        return True
    if host.startswith("10.") or host.startswith("192.168."):
        return True
    if host.startswith("172."):
        # Docker: 172.16.0.0/12
        parts = host.split(".")
        if len(parts) == 4:
            try:
                second = int(parts[1])
                if 16 <= second <= 31:
                    return True
            except ValueError:
                pass
    return False


@app.get("/health")
async def health():
    """Health check"""
    db = next(get_db())
    try:
        # Verificar conexão com banco
        db.execute(text("SELECT 1"))
        db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
    finally:
        db.close()
    
    return {
        "status": "ok",
        "database": db_status,
        "services": {
            "embeddings": "ready",
            "rag": "ready"
        }
    }


# RBAC: publicador ou admin para upload
@app.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    db=Depends(get_db),
    current_user: User = Depends(require_role(["publicador", "admin"])),
):
    """
    Upload de documento
    - Salva o arquivo no filesystem local
    - Extrai o conteúdo
    - Gera embeddings
    - Indexa no Qdrant e salva metadados no PostgreSQL
    """
    try:
        # Validar tipo de arquivo
        allowed_extensions = {'.txt', '.pdf', '.md', '.docx'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de arquivo não suportado. Permitidos: {allowed_extensions}"
            )
        
        # Ler conteúdo do arquivo
        content = await file.read()
        
        # Processar documento através do serviço
        document_service = app.state.document_service
        result = await document_service.process_document(
            filename=file.filename,
            content=content,
            db=db,
            embeddings_service=app.state.embeddings_service,
            qdrant_service=app.state.qdrant_service,
        )
        
        # Auditoria
        try:
            audit = AuditLog(
                action="upload",
                user_id=current_user.id,
                details={"filename": result["filename"], "document_id": result["document_id"]},
            )
            db.add(audit)
            db.commit()
        except Exception:
            pass

        return JSONResponse(
            status_code=201,
            content={
                "message": "Documento processado com sucesso",
                "document_id": result["document_id"],
                "filename": result["filename"],
                "file_path": result["file_path"],
                "content_length": result["content_length"],
                "chunk_count": result.get("chunk_count", 1),
            }
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/internal/upload")
async def internal_upload(
    request: Request,
    file: UploadFile = File(...),
    db=Depends(get_db),
):
    """
    Upload interno para o worker de ingestão.
    Sem auth; aceita apenas requisições da rede interna (Docker/localhost).
    """
    if not _is_internal_request(request):
        raise HTTPException(status_code=403, detail="Acesso negado: endpoint apenas para rede interna")
    try:
        allowed_extensions = {'.txt', '.pdf', '.md', '.docx'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de arquivo não suportado. Permitidos: {allowed_extensions}",
            )
        content = await file.read()
        document_service = app.state.document_service
        result = await document_service.process_document(
            filename=file.filename,
            content=content,
            db=db,
            embeddings_service=app.state.embeddings_service,
            qdrant_service=app.state.qdrant_service,
        )
        return JSONResponse(
            status_code=201,
            content={
                "message": "Documento processado com sucesso",
                "document_id": result["document_id"],
                "filename": result["filename"],
                "file_path": result["file_path"],
                "content_length": result["content_length"],
                "chunk_count": result.get("chunk_count", 1),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ingest/upload")
async def ingest_upload(
    file: UploadFile = File(...),
    db=Depends(get_db),
    x_api_key: Optional[str] = Header(default=None),
):
    if INGEST_API_KEY and x_api_key != INGEST_API_KEY:
        raise HTTPException(status_code=401, detail="API key inválida")
    try:
        allowed_extensions = {'.txt', '.pdf', '.md', '.docx'}
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de arquivo não suportado. Permitidos: {allowed_extensions}",
            )
        content = await file.read()
        result = await app.state.document_service.process_document(
            filename=file.filename,
            content=content,
            db=db,
            embeddings_service=app.state.embeddings_service,
            qdrant_service=app.state.qdrant_service,
        )
        return JSONResponse(
            status_code=201,
            content={
                "message": "Documento ingerido com sucesso",
                "document_id": result["document_id"],
                "filename": result["filename"],
                "file_path": result["file_path"],
                "content_length": result["content_length"],
                "chunk_count": result.get("chunk_count", 1),
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/search", response_model=List[SearchResult])
async def semantic_search(
    request: SearchRequest,
    db=Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Busca semântica usando embeddings
    - Gera embedding da query
    - Busca documentos similares no Qdrant
    - Retorna resultados ordenados por similaridade
    """
    try:
        results = []
        ordered_docs = await _semantic_search_documents(
            db=db,
            embeddings_service=app.state.embeddings_service,
            qdrant_service=app.state.qdrant_service,
            query=request.query,
            limit=request.limit,
            threshold=request.threshold,
        )
        for doc, score in ordered_docs:
            safe_content = _redact_secrets(doc.content or "")
            results.append(
                SearchResult(
                    id=doc.id,
                    filename=doc.filename,
                    content=safe_content[:500] + "..." if len(safe_content) > 500 else safe_content,
                    similarity=_safe_similarity(score),
                    metadata=doc.extra_metadata if doc.extra_metadata else {},
                )
            )
        if results:
            return results

        # Fallback final: varrer arquivos da pasta /data por palavras-chave
        def _filesystem_fallback_search(query_text: str, result_limit: int):
            terms = _build_query_terms(query_text)
            if not terms:
                return []
            allowed_ext = {".txt", ".md"}
            data_path = Path(DATA_DIR)
            if not data_path.exists():
                return []
            ranked = []
            for f in data_path.rglob("*"):
                if not f.is_file() or f.suffix.lower() not in allowed_ext:
                    continue
                try:
                    raw = f.read_text(encoding="utf-8")
                except Exception:
                    try:
                        raw = f.read_text(encoding="latin-1")
                    except Exception:
                        continue
                norm = _strip_accents(raw.lower())
                score = sum(norm.count(t) for t in terms)
                if score <= 0:
                    continue
                ranked.append((score, f.name, raw))
            ranked.sort(key=lambda x: x[0], reverse=True)
            out = []
            for idx, (score, filename, raw) in enumerate(ranked[:result_limit], start=1):
                out.append(SearchResult(
                    id=-idx,
                    filename=filename,
                    content=raw[:500] + "..." if len(raw) > 500 else raw,
                    similarity=float(score),
                    metadata={"source": "data_dir_fallback"},
                ))
            return out

        return await asyncio.to_thread(_filesystem_fallback_search, request.query, request.limit)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/rag", response_model=RAGResponse)
@limiter.limit("30/minute")
async def rag_query(
    request: Request,
    body: RAGRequest,
    db=Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    RAG (Retrieval Augmented Generation)
    - Busca documentos relevantes usando busca semântica
    - Constrói contexto com os documentos encontrados
    - Envia query + contexto para LLM via API
    - Retorna resposta gerada com fontes
    """
    try:
        answer, sources = await _run_rag_flow(
            embeddings_service=app.state.embeddings_service,
            rag_service=app.state.rag_service,
            qdrant_service=app.state.qdrant_service,
            db=db,
            query=body.query,
            limit=body.limit,
            temperature=body.temperature,
        )
        return RAGResponse(answer=answer, sources=sources, query=body.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_rag_flow(
    embeddings_service,
    rag_service,
    qdrant_service,
    db,
    query: str,
    limit: int = 5,
    temperature: float = 0.7,
    max_tokens: int = 4096,
):
    """
    Fluxo RAG reutilizável: busca vetorial + geração de resposta.
    Retorna (answer, sources).
    """
    ordered_docs = await _semantic_search_documents(
        db=db,
        embeddings_service=embeddings_service,
        qdrant_service=qdrant_service,
        query=query,
        limit=limit,
        threshold=0.3,
    )
    sources = []
    context_parts = []
    for doc, score in ordered_docs[:limit]:
        safe_content = _redact_secrets(doc.content or "")
        sources.append(
            SearchResult(
                id=doc.id,
                filename=doc.filename,
                content=safe_content[:500] + "..." if len(safe_content) > 500 else safe_content,
                similarity=_safe_similarity(score),
                metadata=doc.extra_metadata if doc.extra_metadata else {},
            )
        )
        context_parts.append(safe_content)

    context = "\n\n---\n\n".join(context_parts)
    if not sources:
        return ("Não encontrei informações relevantes nos documentos indexados para responder com segurança.", [])
    system_instructions = get_app_setting(db, "rag_instructions", "").strip() or None
    answer = await rag_service.generate_response(
        query=query,
        context=context,
        temperature=temperature,
        max_tokens=max_tokens,
        system_instructions=system_instructions,
    )
    return answer, sources


@app.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Chat com RAG: salva mensagens user/assistant em conversations/messages.
    Se conversation_id ausente, cria nova conversa.
    """
    embeddings_service = app.state.embeddings_service
    rag_service = app.state.rag_service

    if not body.conversation_id:
        conv = Conversation(user_id=current_user.id, title="Nova conversa")
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conversation_id = conv.id
    else:
        conv = db.query(Conversation).filter(
            Conversation.id == body.conversation_id,
            Conversation.user_id == current_user.id
        ).first()
        if not conv:
            raise HTTPException(status_code=404, detail="Conversa não encontrada ou sem permissão")
        conversation_id = conv.id

    answer, sources = await _run_rag_flow(
        embeddings_service,
        rag_service,
        app.state.qdrant_service,
        db,
        body.query,
    )

    sources_json = [{"id": s.id, "filename": s.filename, "content": s.content, "similarity": s.similarity} for s in sources]

    msg_user = Message(conversation_id=conversation_id, role="user", content=body.query)
    db.add(msg_user)
    db.flush()

    msg_assistant = Message(conversation_id=conversation_id, role="assistant", content=answer, sources=sources_json)
    db.add(msg_assistant)

    # Auto-rename na primeira mensagem (título ainda "Nova conversa")
    if conv.title == "Nova conversa":
        user_count = db.query(Message).filter(
            Message.conversation_id == conversation_id,
            Message.role == "user"
        ).count()
        if user_count == 1:
            new_title = await rag_service.summarize_as_title(body.query)
            conv.title = new_title[:500]

    db.commit()
    db.refresh(msg_assistant)
    db.refresh(conv)

    return ChatResponse(
        answer=answer,
        sources=sources,
        conversation_id=conversation_id,
        message_id=msg_assistant.id,
        title=conv.title
    )


@app.post("/v1/chat/completions")
@limiter.limit("60/minute")
async def openai_chat_completions(
    request: Request,
    body: OpenAIChatCompletionRequest,
    db=Depends(get_db),
):
    user_messages = [m.content for m in body.messages if m.role == "user" and m.content]
    if not user_messages:
        raise HTTPException(status_code=400, detail="messages deve conter ao menos uma mensagem de usuário")
    query = user_messages[-1]

    # Tratar histórico para perguntas de follow-up
    history_dicts = [{"role": m.role, "content": m.content} for m in body.messages if m.content]
    search_query = await app.state.rag_service.rewrite_query(history_dicts, query)
    
    # Recuperar contexto RAG usando a pergunta reescrita (caso seja follow-up)
    ordered_docs = await _semantic_search_documents(
        db=db,
        embeddings_service=app.state.embeddings_service,
        qdrant_service=app.state.qdrant_service,
        query=search_query,
        limit=5,
        threshold=0.25,
    )
    context_parts = [_redact_secrets(doc.content or "") for doc, _ in ordered_docs[:5]]
    context = "\n\n---\n\n".join(context_parts)
    system_instructions = get_app_setting(db, "rag_instructions", "").strip() or None

    model_name = body.model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    completion_id = f"chatcmpl-{int(time.time() * 1000)}"

    # Streaming (padrão do Open WebUI)
    if body.stream:
        async def _event_generator():
            async for chunk in app.state.rag_service.generate_response_stream(
                query=query,
                context=context,
                temperature=min(body.temperature, 0.4),
                max_tokens=max(body.max_tokens, 4096),
                system_instructions=system_instructions,
                completion_id=completion_id,
            ):
                yield chunk

        return StreamingResponse(
            _event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # Não-streaming (fallback)
    answer, _ = await _run_rag_flow(
        app.state.embeddings_service,
        app.state.rag_service,
        app.state.qdrant_service,
        db,
        query=query,
        limit=5,
        temperature=min(body.temperature, 0.4),
        max_tokens=max(body.max_tokens, 4096),
    )
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": answer},
                "finish_reason": "stop",
            }
        ],
    }


@app.get("/v1/models")
async def openai_models():
    now = int(time.time())
    groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    models = []
    for model_id in [groq_model, gemini_model]:
        if model_id and model_id not in [m["id"] for m in models]:
            models.append(
                {
                    "id": model_id,
                    "object": "model",
                    "created": now,
                    "owned_by": "rag-data-platform",
                }
            )
    return {"object": "list", "data": models}


def _run_rag_flow_sync(embeddings_service, rag_service, db, query: str, limit: int = 3, temperature: float = 0.7):
    """Versão síncrona para usar com asyncio - na verdade _run_rag_flow é async."""
    pass


@app.get("/conversations", response_model=List[ConversationListItem])
async def list_conversations(
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista conversas do usuário ordenadas por sort_order, created_at DESC."""
    convs = db.query(Conversation).filter(Conversation.user_id == current_user.id).order_by(
        Conversation.sort_order.asc(),
        Conversation.created_at.desc()
    ).all()
    return [
        ConversationListItem(
            id=c.id,
            title=c.title,
            created_at=c.created_at.isoformat() if c.created_at else None
        )
        for c in convs
    ]


@app.get("/conversations/{conv_id}", response_model=ConversationDetail)
async def get_conversation(
    conv_id: int,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Detalhes da conversa + mensagens. Verifica ownership."""
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.user_id == current_user.id
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada ou sem permissão")
    msgs = db.query(Message).filter(Message.conversation_id == conv_id).order_by(Message.created_at.asc()).all()
    return ConversationDetail(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at.isoformat() if conv.created_at else None,
        messages=[
            MessageOut(
                id=m.id, role=m.role, content=m.content,
                created_at=m.created_at.isoformat() if m.created_at else None,
                sources=m.sources
            )
            for m in msgs
        ]
    )


@app.patch("/conversations/reorder")
async def reorder_conversations(
    request: ConversationReorderRequest,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reordena conversas do usuário. order = lista de ids na nova ordem."""
    if not request.order:
        return {"message": "Nenhuma alteração"}
    convs = db.query(Conversation).filter(
        Conversation.user_id == current_user.id,
        Conversation.id.in_(request.order)
    ).all()
    conv_by_id = {c.id: c for c in convs}
    for i, cid in enumerate(request.order):
        if cid in conv_by_id:
            conv_by_id[cid].sort_order = i
    db.commit()
    return {"message": "Ordem atualizada"}


@app.patch("/conversations/{conv_id}", response_model=ConversationListItem)
async def update_conversation(
    conv_id: int,
    request: ConversationUpdateRequest,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atualiza título da conversa."""
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.user_id == current_user.id
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada ou sem permissão")
    if request.title is not None:
        conv.title = (request.title or "Nova conversa")[:500]
    db.commit()
    db.refresh(conv)
    return ConversationListItem(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at.isoformat() if conv.created_at else None
    )


@app.post("/conversations", response_model=ConversationCreateResponse)
async def create_conversation(
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cria nova conversa vazia com title default 'Nova conversa'."""
    conv = Conversation(user_id=current_user.id, title="Nova conversa")
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return ConversationCreateResponse(
        id=conv.id,
        title=conv.title,
        created_at=conv.created_at.isoformat() if conv.created_at else None
    )


@app.delete("/conversations/{conv_id}")
async def delete_conversation(
    conv_id: int,
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Deleta conversa. Verifica ownership."""
    conv = db.query(Conversation).filter(
        Conversation.id == conv_id,
        Conversation.user_id == current_user.id
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversa não encontrada ou sem permissão")
    db.delete(conv)
    db.commit()
    return {"message": "Conversa deletada com sucesso"}


@app.get("/documents")
async def list_documents(
    skip: int = 0,
    limit: int = 10,
    db=Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """Listar documentos indexados (um por arquivo, agrupando chunks)"""
    try:
        from database import Document

        # Mostrar apenas docs raiz (parent_doc_id IS NULL) = 1 registro por arquivo
        base_query = db.query(Document).filter(Document.parent_doc_id.is_(None))
        documents = base_query.order_by(Document.created_at.desc()).offset(skip).limit(limit).all()
        total = base_query.count()
        
        return {
            "total": total,
            "skip": skip,
            "limit": limit,
            "documents": [
                {
                    "id": doc.id,
                    "filename": doc.filename,
                    "file_path": doc.file_path,
                    "created_at": doc.created_at.isoformat() if doc.created_at else None,
                    "has_embedding": doc.embedding is not None
                }
                for doc in documents
            ]
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# RBAC: publicador ou admin para deletar
@app.delete("/documents/{document_id}")
async def delete_document(
    document_id: int,
    db=Depends(get_db),
    current_user: User = Depends(require_role(["publicador", "admin"])),
):
    """Deletar documento"""
    try:
        from database import Document
        
        # Buscar documento
        doc = db.query(Document).filter(Document.id == document_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail="Documento não encontrado")
        
        # Deletar do filesystem local (se existir)
        file_path = doc.file_path
        try:
            if file_path and os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            print(f"Erro ao deletar arquivo local: {e}")

        # Deletar pontos no Qdrant e todos os chunks no banco
        chunk_ids = [d.id for d in db.query(Document).filter(Document.file_path == file_path).all()]
        await app.state.qdrant_service.delete_points(chunk_ids)
        deleted = db.query(Document).filter(Document.file_path == file_path).delete()
        # Auditoria
        try:
            audit = AuditLog(
                action="delete",
                user_id=current_user.id,
                details={"filename": doc.filename, "document_id": document_id},
            )
            db.add(audit)
        except Exception:
            pass
        db.commit()
        
        return {"message": "Documento deletado com sucesso"}
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


# Admin: instruções editáveis
class SettingsResponse(BaseModel):
    rag_instructions: str


class SettingsUpdateRequest(BaseModel):
    rag_instructions: Optional[str] = None


@app.get("/admin/settings", response_model=SettingsResponse)
async def get_admin_settings(
    db=Depends(get_db),
    current_user: User = Depends(require_role(["admin"])),
):
    """Retorna configurações (instruções do assistente). Apenas admin."""
    instructions = get_app_setting(db, "rag_instructions", "")
    return SettingsResponse(rag_instructions=instructions)


@app.patch("/admin/settings", response_model=SettingsResponse)
async def update_admin_settings(
    request: SettingsUpdateRequest,
    db=Depends(get_db),
    current_user: User = Depends(require_role(["admin"])),
):
    """Atualiza instruções do assistente. Apenas admin."""
    if request.rag_instructions is not None:
        set_app_setting(db, "rag_instructions", request.rag_instructions[:2000])
    instructions = get_app_setting(db, "rag_instructions", "")
    return SettingsResponse(rag_instructions=instructions)


# Sincronizar documentos do diretório ./data
DATA_DIR = os.getenv("DATA_DIR", str(Path(BASE_DIR).parent / "data"))


def _sync_files_from_dir(data_path, db, doc_service, emb_service, qdrant_service):
    """Lógica compartilhada de sync: retorna (arquivos_para_processar, skipped)."""
    from pathlib import Path
    storage_path = Path(data_path) / "storage"
    allowed_ext = {".txt", ".pdf", ".md", ".docx"}

    # Nomes já indexados (sem duplicar)
    existing = {
        row[0]
        for row in db.query(Document.filename)
        .filter(Document.parent_doc_id.is_(None))
        .all()
    }

    files_to_process = []
    skipped = 0
    for f in Path(data_path).rglob("*"):
        # Ignorar pasta storage/ (cópias internas já indexadas)
        if storage_path in f.parents or f == storage_path:
            continue
        if not f.is_file() or f.suffix.lower() not in allowed_ext:
            continue
        if f.name in existing:
            skipped += 1
            continue
        files_to_process.append(f)
    return files_to_process, skipped


@app.post("/admin/sync")
async def admin_sync_documents(
    db=Depends(get_db),
    current_user: User = Depends(require_role(["admin"])),
):
    """Processa apenas arquivos novos do DATA_DIR (ignora já indexados). Apenas admin."""
    from pathlib import Path
    data_path = Path(DATA_DIR)
    if not data_path.exists() or not data_path.is_dir():
        return {"message": "Diretório não encontrado", "path": str(data_path), "processed": 0}

    files_to_process, skipped = _sync_files_from_dir(
        data_path, db, app.state.document_service, app.state.embeddings_service, app.state.qdrant_service
    )
    processed = 0
    errors = []
    for f in files_to_process:
        try:
            content = f.read_bytes()
            await app.state.document_service.process_document(
                filename=f.name,
                content=content,
                db=db,
                embeddings_service=app.state.embeddings_service,
                qdrant_service=app.state.qdrant_service,
            )
            processed += 1
        except Exception as e:
            errors.append(f"{f.name}: {str(e)}")
    return {
        "message": f"Sincronização concluída: {processed} novo(s) processado(s), {skipped} já existente(s) ignorado(s).",
        "processed": processed,
        "skipped": skipped,
        "errors": errors[:10],
    }


@app.post("/internal/sync")
async def internal_sync_documents(
    request: Request,
    db=Depends(get_db),
):
    """Processa apenas arquivos novos do DATA_DIR. Sem auth; apenas rede interna (ingestion/Docker)."""
    if not _is_internal_request(request):
        raise HTTPException(status_code=403, detail="Acesso negado: endpoint apenas para rede interna")
    from pathlib import Path
    data_path = Path(DATA_DIR)
    if not data_path.exists() or not data_path.is_dir():
        return {"message": "Diretório não encontrado", "path": str(data_path), "processed": 0}

    files_to_process, skipped = _sync_files_from_dir(
        data_path, db, app.state.document_service, app.state.embeddings_service, app.state.qdrant_service
    )
    processed = 0
    errors = []
    for f in files_to_process:
        try:
            content = f.read_bytes()
            await app.state.document_service.process_document(
                filename=f.name,
                content=content,
                db=db,
                embeddings_service=app.state.embeddings_service,
                qdrant_service=app.state.qdrant_service,
            )
            processed += 1
        except Exception as e:
            errors.append(f"{f.name}: {str(e)}")
    return {
        "message": f"Sincronização concluída: {processed} novo(s) processado(s), {skipped} já existente(s) ignorado(s).",
        "processed": processed,
        "skipped": skipped,
        "errors": errors[:10],
    }


# RBAC: só admin
@app.get("/admin/users")
async def list_admin_users(
    skip: int = 0,
    limit: int = 50,
    db=Depends(get_db),
    current_user: User = Depends(require_role(["admin"])),
):
    """Listar usuários (apenas admin)."""
    total = db.query(User).count()
    users = db.query(User).order_by(User.created_at.desc()).offset(skip).limit(limit).all()
    return {
        "total": total,
        "skip": skip,
        "limit": limit,
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "name": u.name or "",
                "role": u.role or "leitor",
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
    }
