"""
init_db.py — 최초 1회만 실행하세요.
관리자 계정 + 원료 20개 초기 데이터를 Supabase에 등록합니다.

실행 방법:
  pip install supabase
  python init_db.py
"""

import hashlib, secrets
from supabase import create_client

# ── Supabase 접속 정보 입력 ───────────────────────────────────
SUPABASE_URL = "https://htctznzgpjildklfiret.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Imh0Y3R6bnpncGppbGRrbGZpcmV0Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3OTI4MzYyOSwiZXhwIjoyMDk0ODU5NjI5fQ.tXFfdeD23XmG-TGsOOr3_HQzw-2cojqBNliaIgMfh9s"

# ─────────────────────────────────────────────────────────────
sb = create_client(SUPABASE_URL, SUPABASE_KEY)

def hash_pw(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 100_000)
    return f"{salt}:{h.hex()}"

# ── 초기 사용자 ───────────────────────────────────────────────
INIT_USERS = [
    {"username": "admin",   "password": "admin123",  "name": "관리자",    "role": "admin"},
    {"username": "qc_user", "password": "user123",   "name": "QC 담당자", "role": "user"},
]

# ── 원료 20종 ─────────────────────────────────────────────────
INIT_MATERIALS = [
    {"code": "1001308", "name": "Sildenafil Citrate",                          "usl": 102.0, "lsl": 98.0},
    {"code": "1000564", "name": "대웅에포시스원액",                              "usl": 105.0, "lsl": 95.0},
    {"code": "1000525", "name": "Thiamine Nitrate",                            "usl": 103.0, "lsl": 97.0},
    {"code": "1000507", "name": "Simethicone Liquid",                          "usl": 103.0, "lsl": 97.0},
    {"code": "1000336", "name": "Minocycline Hydrochloride",                   "usl": 103.0, "lsl": 97.0},
    {"code": "1000295", "name": "Sodium Dihydrogen Phosphate Dihydrate",       "usl": 103.0, "lsl": 97.0},
    {"code": "1000263", "name": "Folic Acid",                                  "usl": 103.0, "lsl": 97.0},
    {"code": "1000251", "name": "소마트로핀 원액(바이넥스)",                     "usl": 103.0, "lsl": 97.0},
    {"code": "1000244", "name": "Entecavir",                                   "usl": 103.0, "lsl": 97.0},
    {"code": "1000211", "name": "Selenium in Dried Yeast",                     "usl": 103.0, "lsl": 97.0},
    {"code": "1000204", "name": "0.1% Cyanocobalamine Powder",                 "usl": 103.0, "lsl": 97.0},
    {"code": "1000203", "name": "Cyanocobalamine 1% Powder",                   "usl": 103.0, "lsl": 97.0},
    {"code": "1000202", "name": "0.1% Cyanocobalamin",                         "usl": 103.0, "lsl": 97.0},
    {"code": "1000190", "name": "Chromium in Dried Yeast(Red Star Yeast)",     "usl": 103.0, "lsl": 97.0},
    {"code": "1300524", "name": "Rosuvastatin Calcium",                        "usl": 103.0, "lsl": 97.0},
    {"code": "1300433", "name": "Cholecalciferol Concentrate (Powder Form)",   "usl": 103.0, "lsl": 97.0},
    {"code": "1300353", "name": "히드록소코발라민아세트산염(KP,Interquim)",      "usl": 103.0, "lsl": 97.0},
    {"code": "1300351", "name": "Pyridoxal Phosphate Hydrate",                 "usl": 103.0, "lsl": 97.0},
    {"code": "1300156", "name": "Ezetimibe",                                   "usl": 103.0, "lsl": 97.0},
    {"code": "1300103", "name": "Olmesartan medoxomil (Interquim)",            "usl": 103.0, "lsl": 97.0},
]

# Sildenafil Citrate 초기 데이터 15개
SILDENAFIL_DATA = [
    {"lot_no": "156006I", "value": 100.5},
    {"lot_no": "156679I", "value": 99.8},
    {"lot_no": "160901I", "value": 99.8},
    {"lot_no": "163924I", "value": 99.2},
    {"lot_no": "167366I", "value": 100.4},
    {"lot_no": "171558I", "value": 100.3},
    {"lot_no": "172277I", "value": 100.2},
    {"lot_no": "174865I", "value": 100.5},
    {"lot_no": "176430I", "value": 101.0},
    {"lot_no": "178340I", "value": 99.5},
    {"lot_no": "178860I", "value": 100.9},
    {"lot_no": "182363I", "value": 99.9},
    {"lot_no": "184669I", "value": 100.1},
    {"lot_no": "189842I", "value": 100.4},
    {"lot_no": "190576I", "value": 101.4},
]

def run():
    print("=" * 50)
    print("  QC OOT 시스템 — 초기 데이터 등록")
    print("=" * 50)

    # 사용자 등록
    print("\n[1] 사용자 등록 중...")
    for u in INIT_USERS:
        existing = sb.table('users').select('id').eq('username', u['username']).execute().data
        if existing:
            print(f"  SKIP  {u['username']} (이미 존재)")
        else:
            sb.table('users').insert({
                'username':      u['username'],
                'password_hash': hash_pw(u['password']),
                'name':          u['name'],
                'role':          u['role'],
            }).execute()
            print(f"  OK    {u['username']} ({u['role']})")

    # 원료 등록
    print("\n[2] 원료 등록 중...")
    for m in INIT_MATERIALS:
        existing = sb.table('materials').select('id').eq('code', m['code']).execute().data
        if existing:
            print(f"  SKIP  {m['code']} — {m['name']} (이미 존재)")
        else:
            sb.table('materials').insert(m).execute()
            print(f"  OK    {m['code']} — {m['name']}")

    # Sildenafil 초기 시험 결과 등록
    print("\n[3] Sildenafil Citrate 시험 결과 15개 등록 중...")
    for row in SILDENAFIL_DATA:
        existing = sb.table('test_results')\
            .select('id').eq('material_code','1001308').eq('lot_no', row['lot_no']).execute().data
        if existing:
            print(f"  SKIP  {row['lot_no']} (이미 존재)")
        else:
            sb.table('test_results').insert({
                'material_code': '1001308',
                'lot_no':        row['lot_no'],
                'value':         row['value'],
            }).execute()
            print(f"  OK    {row['lot_no']} = {row['value']}")

    print("\n✅ 초기화 완료!")
    print("\n기본 계정 정보:")
    print("  관리자: admin / admin123")
    print("  사용자: qc_user / user123")
    print("\n⚠️  반드시 첫 로그인 후 비밀번호를 변경하세요.")

if __name__ == "__main__":
    run()
