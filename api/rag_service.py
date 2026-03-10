"""
Serviço RAG (Retrieval Augmented Generation) com cascata de provedores LLM.

Ordem de fallback:
1. Groq (api.groq.com) - llama-3.1-8b-instant ou mistral-7b-instruct
2. Google Gemini Flash - quando Groq retornar 429 ou erro
"""

import httpx
import os
import re
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Constantes dos provedores
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


class RAGService:
    """Serviço para geração de respostas usando RAG com cascata de LLMs"""

    def __init__(self, base_url: str = None, model: str = None):
        """Inicializar serviço RAG (Groq/Gemini)."""
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.gemini_model = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

        self.client = httpx.AsyncClient(timeout=120.0)

    async def generate_response(
        self,
        query: str,
        context: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        system_instructions: Optional[str] = None,
    ) -> str:
        """
        Gerar resposta usando RAG com cascata de provedores.
        Ordem: Groq (com retry em 429) -> Gemini

        Returns:
            Resposta gerada pelo LLM, ou mensagem amigável se todos falharem.
        """
        prompt = self._build_rag_prompt(query, context, system_instructions)

        # 1) Tentar Groq — com 1 retry em caso de rate limit (429)
        if os.getenv("GROQ_API_KEY"):
            for attempt in range(2):
                try:
                    raw = await self._call_groq(prompt, temperature, max_tokens)
                    return self._postprocess_answer(raw)
                except Exception as exc:
                    err = str(exc)
                    if "429" in err and attempt == 0:
                        logger.warning("Groq rate limit (429). Aguardando 3s antes de retry...")
                        await asyncio.sleep(3)
                        continue
                    logger.warning("Groq falhou (tentativa %d): %s", attempt + 1, exc)
                    break

        # 2) Tentar Gemini
        if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
            try:
                raw = await self._call_gemini(prompt, temperature, max_tokens)
                return self._postprocess_answer(raw)
            except Exception as exc:
                logger.warning("Gemini falhou: %s", exc)

        # Todos os provedores falharam — retornar mensagem amigável em vez de 500
        logger.error("Nenhum provedor LLM disponível para responder a query.")
        return (
            "Desculpe, o serviço de respostas está temporariamente sobrecarregado. "
            "Por favor, aguarde alguns segundos e tente novamente."
        )


    def _postprocess_answer(self, answer: str) -> str:
        """
        Sanitiza respostas para reduzir passos inventados/incompletos.
        Regras:
        - Em listas numeradas, remove itens com marcadores de incerteza/filler.
        - Se um item removido era o último da sequência, encerra naturalmente no passo anterior.
        """
        if not answer or not answer.strip():
            return answer

        lines = answer.splitlines()
        numbered_re = re.compile(r"^\s*(\d+)[\.\)]\s+")
        uncertainty_re = re.compile(
            r"(\.\.\.|não\s+especificad|a\s+definir|a\s+confirmar|depende|etc\.?)",
            re.IGNORECASE,
        )

        cleaned = []
        removed_steps = set()
        for line in lines:
            m = numbered_re.match(line)
            if m and uncertainty_re.search(line):
                removed_steps.add(int(m.group(1)))
                continue
            cleaned.append(line)

        # Remove linhas em branco extras geradas pela limpeza
        out = "\n".join(cleaned)
        out = re.sub(r"\n{3,}", "\n\n", out).strip()
        return out or answer.strip()

    async def summarize_as_title(self, text: str, max_words: int = 6) -> str:
        """
        Resume o texto em um título curto (estilo ChatGPT/Gemini).
        Usado para auto-renomear conversas na primeira mensagem.
        Fallback: truncar em ~40 chars no último espaço se LLM falhar.
        """
        if not text or not text.strip():
            return "Nova conversa"
        text = text.strip()
        prompt = f"""Resuma em no máximo {max_words} palavras, em português, apenas o título sem aspas ou pontuação final:
{text}

Título:"""
        def _normalize_title(raw: str) -> str:
            cleaned = " ".join((raw or "").replace('"', "").replace("'", "").split()).strip()
            if not cleaned:
                return "Nova conversa"
            words = cleaned.split(" ")[:max_words]
            title = " ".join(words).strip().rstrip(".,;:!?")
            return (title[:80].strip() or "Nova conversa")

        try:
            if os.getenv("GROQ_API_KEY"):
                try:
                    out = await self._call_groq(prompt, temperature=0.3, max_tokens=30)
                    if out and len(out) < 80:
                        return _normalize_title(out)
                except Exception:
                    pass
            if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
                try:
                    out = await self._call_gemini(prompt, temperature=0.3, max_tokens=30)
                    if out and len(out) < 80:
                        return _normalize_title(out)
                except Exception:
                    pass
        except Exception:
            pass
        # Fallback heurístico
        return _normalize_title(text)

    async def rewrite_query(self, history: list[dict], query: str) -> str:
        """
        Reescreve uma pergunta de follow-up (ex: 'e essas duas?') para ser 
        autocontida usando o histórico da conversa.
        Se a pergunta já for independente ou não houver histórico, retorna a original.
        """
        if not history or len(history) < 2:
            return query
            
        # Pega as últimas 3 mensagens para dar contexto (sem sobrecarregar)
        recent = history[-3:]
        chat_log = "\n".join([f"{msg.get('role', 'user').upper()}: {msg.get('content', '')}" for msg in recent])
        
        prompt = f"""Dada a conversa abaixo e a pergunta de acompanhamento final, reescreva a pergunta de acompanhamento para que ela seja uma pergunta isolada e auto-explicativa, incluindo os sujeitos ocultos (como nomes de sistemas, projetos ou entidades mencionadas antes).
Se a pergunta final já for clara e não depender do histórico, apenas repita-a. 
NÃO responda a pergunta, apenas REESCREVA a pergunta.

CONVERSA:
{chat_log}

PERGUNTA DE ACOMPANHAMENTO: {query}

PERGUNTA REESCRITA (apenas a pergunta):"""

        try:
            if os.getenv("GROQ_API_KEY"):
                try:
                    out = await self._call_groq(prompt, temperature=0.1, max_tokens=60)
                    if out: return out
                except Exception:
                    pass
            if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
                try:
                    out = await self._call_gemini(prompt, temperature=0.1, max_tokens=60)
                    if out: return out
                except Exception:
                    pass
        except Exception:
            pass
        return query

    async def _call_groq(
        self, prompt: str, temperature: float, max_tokens: int
    ) -> str:
        """Chamar Groq API (api.groq.com)"""
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY não configurada")

        response = await self.client.post(
            f"{GROQ_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )

        if response.status_code == 429:
            raise Exception("Groq: rate limit (429)")

        response.raise_for_status()
        result = response.json()
        choice = result.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")
        if content:
            return content.strip()
        raise Exception("Groq: resposta vazia")

    async def generate_response_stream(
        self,
        query: str,
        context: str,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        system_instructions: Optional[str] = None,
        completion_id: str = "",
    ):
        """
        Gera resposta em streaming (Server-Sent Events, formato OpenAI).
        Tenta Groq stream primeiro; se falhar, faz pseudo-stream da resposta completa.

        Yields: bytes de cada chunk SSE
        """
        import json as _json
        import time as _time

        cid = completion_id or f"chatcmpl-{int(_time.time() * 1000)}"
        model = self.groq_model
        created = int(_time.time())

        def _make_chunk(content: str, finish_reason=None) -> bytes:
            delta = {"content": content} if content else {}
            chunk = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            }
            return f"data: {_json.dumps(chunk)}\n\n".encode()

        prompt = self._build_rag_prompt(query, context, system_instructions)
        api_key = os.getenv("GROQ_API_KEY")
        streamed_ok = False

        if api_key:
            for attempt in range(2):
                try:
                    async with self.client.stream(
                        "POST",
                        f"{GROQ_BASE_URL}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": self.groq_model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                            "stream": True,
                        },
                    ) as resp:
                        if resp.status_code == 429:
                            if attempt == 0:
                                logger.warning("Groq 429 no stream. Retry em 3s...")
                                await asyncio.sleep(3)
                                continue
                            break
                        resp.raise_for_status()
                        async for line in resp.aiter_lines():
                            if not line or not line.startswith("data:"):
                                continue
                            raw = line[len("data:"):].strip()
                            if raw == "[DONE]":
                                break
                            try:
                                obj = _json.loads(raw)
                                delta = obj["choices"][0].get("delta", {})
                                text = delta.get("content", "")
                                if text:
                                    yield _make_chunk(text)
                            except Exception:
                                continue
                        streamed_ok = True
                        break
                except Exception as exc:
                    logger.warning("Groq stream falhou (tentativa %d): %s", attempt + 1, exc)
                    if attempt == 0:
                        await asyncio.sleep(3)

        if not streamed_ok:
            # Fallback: gerar resposta completa e pseudo-streamear
            full = await self.generate_response(
                query, context, temperature, max_tokens, system_instructions
            )
            # Enviar em pedaços de ~4 chars para simular typewriter
            chunk_size = 4
            for i in range(0, len(full), chunk_size):
                yield _make_chunk(full[i: i + chunk_size])
                await asyncio.sleep(0.01)

        # Chunk final com finish_reason
        yield _make_chunk("", finish_reason="stop")
        yield b"data: [DONE]\n\n"



    async def _call_gemini(
        self, prompt: str, temperature: float, max_tokens: int
    ) -> str:
        """Chamar Google Gemini API"""
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY ou GEMINI_API_KEY não configuradas")

        url = (
            f"{GEMINI_BASE_URL}/models/{self.gemini_model}:generateContent"
            f"?key={api_key}"
        )
        payload = {
            "contents": [
                {
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        response = await self.client.post(url, json=payload)
        response.raise_for_status()
        result = response.json()

        candidates = result.get("candidates", [])
        if not candidates:
            raise Exception("Gemini: nenhum candidato na resposta")

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            raise Exception("Gemini: resposta vazia")

        text = parts[0].get("text", "")
        return text.strip() if text else ""

    def _build_rag_prompt(self, query: str, context: str, system_instructions: Optional[str] = None) -> str:
        """
        Construir prompt RAG com contexto

        Args:
            query: Pergunta do usuário
            context: Contexto dos documentos
            system_instructions: Instruções customizadas (substituem as padrão se fornecidas)

        Returns:
            Prompt formatado
        """
        default_instructions = """- Responda a pergunta usando APENAS as informações do contexto fornecido
- Se a informação não estiver no contexto, responda EXATAMENTE: "Não encontrei essa informação na base de conhecimento. Tente reformular a pergunta ou consulte o responsável técnico."
- NÃO invente, especule nem acrescente passos, URLs, nomes de times, commandos ou ambientes que não estejam explicitamente no contexto
- Se o contexto vier de um documento T2R (Transfer to Run), mencione que as informações podem estar incompletas
- Se houver informações conflitantes entre partes do contexto, mencione a divergência ao invés de escolher uma versão
- Escreva uma resposta única e fluida. NÃO use cabeçalhos (#, ##) nem seções como "Resposta Direta", "Resumo" etc.
- Use bullet points apenas quando a pergunta for sobre uma lista de itens ou passos; caso contrário, use prosa
- Inclua código em bloco ``` apenas quando a pergunta for sobre implementação ou comandos específicos
- NÃO cite nomes de arquivos da base (.txt, .pdf, .docx). O usuário não precisa saber a origem
- Em respostas sobre processos/fluxos, pare no último passo confirmado pelo contexto; não adicione etapas genéricas
- Nunca escreva "não especificado", "a definir" ou similar — se não tiver a info, omita aquele ponto
- Use markdown inline: código em `backticks`, nomes de arquivo em _itálico_"""
        custom_instructions = (system_instructions or "").strip()
        if custom_instructions:
            instructions = (
                f"{default_instructions}\n"
                f"- Instruções adicionais do administrador (aplicar sem violar as regras acima):\n"
                f"{custom_instructions}"
            )
        else:
            instructions = default_instructions
        return f"""Você é um assistente útil que responde perguntas baseado no contexto fornecido.

CONTEXTO:
{context}

PERGUNTA: {query}

INSTRUÇÕES:
{instructions}

RESPOSTA:"""

