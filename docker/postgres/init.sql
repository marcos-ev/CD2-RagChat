-- Habilitar extensão pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Criar tabela para armazenar documentos e embeddings
CREATE TABLE IF NOT EXISTS documents (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    file_path VARCHAR(500) NOT NULL,
    content TEXT,
    embedding vector(384),  -- Dimensão padrão para sentence-transformers/all-MiniLM-L6-v2
    metadata JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Criar índice HNSW para busca vetorial eficiente
CREATE INDEX IF NOT EXISTS documents_embedding_idx ON documents 
USING hnsw (embedding vector_cosine_ops);

-- Criar índice para busca por filename
CREATE INDEX IF NOT EXISTS documents_filename_idx ON documents (filename);

-- Criar função para atualizar updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Criar trigger para atualizar updated_at automaticamente
CREATE TRIGGER update_documents_updated_at BEFORE UPDATE ON documents
FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- Tabelas para usuários, conversas e mensagens
-- ============================================

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    name VARCHAR(255) DEFAULT '',
    role VARCHAR(50) DEFAULT 'leitor',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Migração: adicionar coluna name se não existir (para instalações antigas)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'name') THEN
        ALTER TABLE users ADD COLUMN name VARCHAR(255) DEFAULT '';
    END IF;
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'users' AND column_name = 'role') THEN
        UPDATE users SET role = 'leitor' WHERE role = 'user' OR role IS NULL;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS conversations (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title VARCHAR(500) DEFAULT 'Nova conversa',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS conversations_user_id_idx ON conversations (user_id);

CREATE TABLE IF NOT EXISTS messages (
    id SERIAL PRIMARY KEY,
    conversation_id INT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    sources JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS messages_conversation_id_idx ON messages (conversation_id);

-- Migração: adicionar sort_order em conversations para reordenação
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'conversations' AND column_name = 'sort_order') THEN
        ALTER TABLE conversations ADD COLUMN sort_order INT DEFAULT 0;
        UPDATE conversations SET sort_order = id;
    END IF;
END
$$;

-- ============================================
-- Alterações em documents para suportar chunks
-- ============================================

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'documents' AND column_name = 'chunk_index') THEN
        ALTER TABLE documents ADD COLUMN chunk_index INT DEFAULT 0;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_schema = 'public' AND table_name = 'documents' AND column_name = 'parent_doc_id') THEN
        ALTER TABLE documents ADD COLUMN parent_doc_id INT REFERENCES documents(id) ON DELETE SET NULL;
    END IF;
END
$$;

