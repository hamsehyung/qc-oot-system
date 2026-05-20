-- ============================================================
--  QC OOT 관리 시스템 — Supabase 테이블 생성 SQL
--  Supabase > SQL Editor 에서 전체 복사 후 실행하세요.
-- ============================================================

-- 1. 사용자 테이블
CREATE TABLE IF NOT EXISTS users (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name          TEXT NOT NULL,
    role          TEXT DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 원료 테이블
CREATE TABLE IF NOT EXISTS materials (
    id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    code       TEXT UNIQUE NOT NULL,
    name       TEXT NOT NULL,
    usl        FLOAT NOT NULL,
    lsl        FLOAT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. 시험 결과 테이블
CREATE TABLE IF NOT EXISTS test_results (
    id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    material_code TEXT REFERENCES materials(code) ON DELETE CASCADE,
    lot_no        TEXT NOT NULL,
    value         FLOAT NOT NULL,
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(material_code, lot_no)
);

-- 4. Audit Trail 테이블
CREATE TABLE IF NOT EXISTS audit_trail (
    id         UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    user_id    TEXT NOT NULL,
    user_name  TEXT NOT NULL,
    action     TEXT NOT NULL,
    detail     TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스 (성능 향상)
CREATE INDEX IF NOT EXISTS idx_test_results_mat  ON test_results(material_code);
CREATE INDEX IF NOT EXISTS idx_audit_created      ON audit_trail(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_user         ON audit_trail(user_id);

-- ============================================================
--  RLS(Row Level Security) 비활성화
--  ※ 앱 자체에서 인증을 처리하므로 RLS는 끕니다.
-- ============================================================
ALTER TABLE users        DISABLE ROW LEVEL SECURITY;
ALTER TABLE materials    DISABLE ROW LEVEL SECURITY;
ALTER TABLE test_results DISABLE ROW LEVEL SECURITY;
ALTER TABLE audit_trail  DISABLE ROW LEVEL SECURITY;
