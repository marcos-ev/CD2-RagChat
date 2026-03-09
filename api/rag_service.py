"""
Serviço RAG (Retrieval Augmented Generation) com cascata de provedores LLM.

Ordem de fallback:
1. Groq (api.groq.com) - llama-3.1-8b-instant ou mistral-7b-instruct
2. Google Gemini Flash - quando Groq retornar 429 ou erro
"""

import httpx
import os
import re
from typing import Optional


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
        max_tokens: int = 512,
        system_instructions: Optional[str] = None,
    ) -> str:
        """
        Gerar resposta usando RAG com cascata de provedores.

        Ordem: Groq -> Gemini

        Args:
            query: Pergunta do usuário
            context: Contexto retornado pela busca semântica
            temperature: Temperatura para geração (0.0-1.0)
            max_tokens: Número máximo de tokens na resposta
            system_instructions: Instruções customizadas (opcional)

        Returns:
            Resposta gerada pelo LLM
        """
        prompt = self._build_rag_prompt(query, context, system_instructions)

        # 1) Tentar Groq (pula se GROQ_API_KEY não configurada)
        if os.getenv("GROQ_API_KEY"):
            try:
                raw = await self._call_groq(prompt, temperature, max_tokens)
                return self._postprocess_answer(raw)
            except Exception:
                pass

        # 2) Tentar Gemini (pula se GOOGLE_API_KEY/GEMINI_API_KEY não configuradas)
        if os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"):
            try:
                raw = await self._call_gemini(prompt, temperature, max_tokens)
                return self._postprocess_answer(raw)
            except Exception:
                pass

        raise Exception(
            "Nenhum provedor LLM disponível: configure GROQ_API_KEY ou GOOGLE_API_KEY/GEMINI_API_KEY."
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
- Se a resposta não estiver no contexto, diga que não tem informações suficientes
- Seja objetivo, mas com contexto técnico suficiente quando a pergunta pedir detalhe
- Dê a resposta direta primeiro; depois complemente apenas o que for relevante
- Não invente etapas, nomes de times, ambientes, comandos, URLs ou procedimentos que não estejam no contexto
- Em respostas em formato de processo/lista, pare no último passo confirmado pelo contexto; não adicione um "próximo passo padrão" só para completar
- Se houver lacuna em parte crítica, declare brevemente que faltam informações para esse trecho, sem criar conteúdo hipotético
- NÃO cite o nome do arquivo textual base de ingestão como fonte (ex: arquivos .txt da pasta de dados)
- Quando houver no contexto o caminho técnico real do alvo da pergunta, pode citá-lo explicitamente na resposta (ex: src/infra/http/controllers/journey-passai-responses/PassaiCard.json)
- Se a pergunta for sobre implementação, pode incluir um bloco curto de código relevante
- Nunca escreva "não especificado" ou similar; se não tiver a informação, omita aquele ponto
- Use markdown: código em blocos ``` ou `inline`, nomes de arquivo em _itálico_"""
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

