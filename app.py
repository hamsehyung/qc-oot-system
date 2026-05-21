# ============================================================
#  QC OOT 관리 시스템
#  Streamlit + Supabase
# ============================================================
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import hashlib, secrets, re, io, base64
from datetime import datetime, timedelta
from supabase import create_client, Client
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ─── Page Config ─────────────────────────────────────────────
st.set_page_config(
    page_title="QC OOT 관리 시스템",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── Custom CSS ───────────────────────────────────────────────
st.markdown("""
<style>
  .header-box {
    background: linear-gradient(90deg, #1e3a5f 0%, #1e40af 100%);
    color: white; padding: 14px 22px; border-radius: 12px;
    margin-bottom: 18px;
  }
  .stat-box {
    background: #f8fafc; border: 1px solid #e2e8f0;
    border-radius: 8px; padding: 9px 13px; margin: 3px 0;
    display: flex; justify-content: space-between;
    font-size: 13px;
  }
  .badge-pass { background:#d1fae5; color:#065f46;
    padding:2px 10px; border-radius:10px; font-weight:700; font-size:12px; }
  .badge-oot  { background:#fef3c7; color:#92400e;
    padding:2px 10px; border-radius:10px; font-weight:700; font-size:12px; }
  .badge-oos  { background:#fee2e2; color:#991b1b;
    padding:2px 10px; border-radius:10px; font-weight:700; font-size:12px; }
  [data-testid="stSidebar"] { background: #f0f4ff; }
  div[data-testid="stMetricValue"] > div { font-size: 17px !important; }
</style>
""", unsafe_allow_html=True)

# ─── Supabase Client ──────────────────────────────────────────
@st.cache_resource
def get_sb() -> Client:
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])

sb = get_sb()

# ─── Password Utilities ───────────────────────────────────────
def hash_pw(pw: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 100_000)
    return f"{salt}:{h.hex()}"

def verify_pw(pw: str, stored: str) -> bool:
    """평문 및 해시(salt:hash) 모두 지원하는 비밀번호 검증"""
    if not stored:
        return False
    # 1순위: 평문 직접 비교 (DB에 admin123 그대로 있을 때)
    if pw == stored:
        return True
    # 2순위: salt:hash 형식 해시 비교
    if ':' in stored:
        try:
            salt, h = stored.split(':', 1)
            test = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 100_000)
            if test.hex() == h:
                return True
        except Exception:
            pass
    return False

# ─── Statistics ───────────────────────────────────────────────
def parse_lot(lot: str) -> int:
    m = re.match(r'^(\d+)', str(lot))
    return int(m.group(1)) if m else 0

def calc_stats(values: list, usl: float, lsl: float) -> dict | None:
    if not values:
        return None
    arr = np.array([float(v) for v in values])
    n = len(arr)
    mean = float(np.mean(arr))
    sd   = float(np.std(arr, ddof=1)) if n > 1 else 0.0
    rsd  = (sd / mean * 100) if mean else 0.0
    vmin, vmax = float(np.min(arr)), float(np.max(arr))

    if n < 5:                         # 데이터 5개 미만 → Min/Max 기준
        ucl, lcl = vmax, vmin
    else:                             # 5개 이상 → 2σ 기준
        ucl = mean + 2 * sd
        lcl = mean - 2 * sd

    cp  = (usl - lsl) / (6 * sd) if sd > 0 else None
    cpk = min((usl - mean) / (3 * sd), (mean - lsl) / (3 * sd)) if sd > 0 else None

    return dict(n=n, mean=mean, sd=sd, rsd=rsd,
                vmin=vmin, vmax=vmax, ucl=ucl, lcl=lcl,
                cp=cp, cpk=cpk)

def get_status(v: float, st_: dict | None, usl: float, lsl: float) -> str:
    if st_ is None:
        return "데이터 부족"
    if v > usl or v < lsl:
        return "OOS"
    if v > st_['ucl'] or v < st_['lcl']:
        return "OOT"
    return "Pass"

# ─── Audit Log ────────────────────────────────────────────────
def log_audit(action: str, detail: str):
    if 'user' not in st.session_state:
        return
    u = st.session_state.user
    try:
        sb.table('audit_trail').insert({
            'user_id':   u['username'],
            'user_name': u['name'],
            'action':    action,
            'detail':    detail,
            'created_at': datetime.now().isoformat()
        }).execute()
    except Exception:
        pass

# ─── DB Helpers ───────────────────────────────────────────────
def get_materials():
    return sb.table('materials').select('*').order('code').execute().data

def get_results(mat_code: str):
    rows = sb.table('test_results').select('*').eq('material_code', mat_code).execute().data
    rows.sort(key=lambda x: parse_lot(x['lot_no']))
    return rows

def get_users():
    return sb.table('users').select('id,username,name,role').execute().data

def authenticate(username: str, password: str):
    try:
        rows = sb.table('users').select('*').eq('username', username).execute().data
    except Exception as e:
        st.error(f"DB 연결 오류: {e}")
        return None
    if not rows:
        return None
    u = rows[0]
    stored_pw = u.get('password_hash', '')
    return u if verify_pw(password, stored_pw) else None

# ─── Report Generation ────────────────────────────────────────
def make_chart_image(chart_data, stats, usl, lsl):
    """추세 차트를 matplotlib PNG → base64 변환"""
    fig, ax = plt.subplots(figsize=(14, 3.5))
    existing = [d for d in chart_data if not d.get('new')]
    new_pts  = [d for d in chart_data if d.get('new')]

    if existing:
        xs = [d['lot_no'] for d in existing]
        ys = [d['value']  for d in existing]
        ax.plot(xs, ys, '-', color='#3b82f6', linewidth=1.8, zorder=2)
        for x, y in zip(xs, ys):
            s = get_status(y, stats, usl, lsl) if stats else 'Pass'
            c = {'Pass':'#10b981','OOT':'#f59e0b','OOS':'#ef4444'}.get(s,'#6b7280')
            ax.scatter(x, y, color=c, s=55, zorder=3, edgecolors='white', linewidths=1.2)

    if new_pts:
        s = get_status(new_pts[0]['value'], stats, usl, lsl) if stats else 'Pass'
        c = {'Pass':'#10b981','OOT':'#f59e0b','OOS':'#ef4444'}.get(s,'#6b7280')
        ax.scatter(new_pts[0]['lot_no'], new_pts[0]['value'],
                   marker='*', s=280, color=c, zorder=4,
                   edgecolors='#1d4ed8', linewidths=1.5, label='★ New')

    if stats:
        ax.axhline(stats['ucl'],  color='#f59e0b', ls='--', lw=1.2, label=f"UCL {stats['ucl']:.2f}")
        ax.axhline(stats['lcl'],  color='#f59e0b', ls='--', lw=1.2, label=f"LCL {stats['lcl']:.2f}")
        ax.axhline(stats['mean'], color='#3b82f6', ls=':',  lw=1.0, label=f"Mean {stats['mean']:.2f}")
    ax.axhline(usl, color='#10b981', ls='-.', lw=1.2, label=f"USL {usl}")
    ax.axhline(lsl, color='#10b981', ls='-.', lw=1.2, label=f"LSL {lsl}")

    ax.set_xlabel('Lot No.', fontsize=8)
    ax.set_ylabel('Result', fontsize=8)
    ax.tick_params(axis='x', rotation=30, labelsize=7)
    ax.tick_params(axis='y', labelsize=8)
    ax.legend(loc='upper right', fontsize=7, ncol=5, framealpha=0.8)
    ax.set_facecolor('#f9fafb')
    ax.grid(True, alpha=0.25)
    fig.tight_layout(pad=0.5)

    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=130, bbox_inches='tight')
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode()


def build_report_html(mat, results, stats, prev, current_user):
    """A4 출력용 HTML 레포트 생성"""
    now        = datetime.now().strftime('%Y년 %m월 %d일  %H:%M')
    doc_no     = f"QC-OOT-{datetime.now().strftime('%Y%m%d%H%M')}"
    usl, lsl   = float(mat['usl']), float(mat['lsl'])
    status     = prev['status'] if prev else None

    sc = {'Pass':'#059669','OOT':'#d97706','OOS':'#dc2626'}
    sb_c = {'Pass':'#d1fae5','OOT':'#fef3c7','OOS':'#fee2e2'}
    icon = {'Pass':'✅','OOT':'⚠️','OOS':'🚨'}

    # 추세 차트 이미지
    chart_data = [{'lot_no':r['lot_no'],'value':r['value'],'new':False} for r in results]
    if prev:
        chart_data.append({'lot_no':prev['lot_no'],'value':prev['value'],'new':True})
    chart_b64 = make_chart_image(chart_data, stats, usl, lsl) if chart_data else None

    # 시험 데이터 행
    def st_color(v):
        s = get_status(v, stats, usl, lsl) if stats else '—'
        return sc.get(s,'#374151'), s
    data_rows = ''.join([
        f'<tr><td>{i+1}</td><td style="font-family:monospace">{r["lot_no"]}</td>'
        f'<td style="text-align:right">{r["value"]}</td>'
        f'<td style="color:{st_color(r["value"])[0]};font-weight:700">{st_color(r["value"])[1]}</td></tr>'
        for i,r in enumerate(results)
    ])

    # 통계 아이템
    def si(label, val, color='#111827'):
        return f'<div class="si"><div class="sl">{label}</div><div class="sv" style="color:{color}">{val}</div></div>'

    stat_items = ''
    if stats:
        s = stats
        stat_items = (
            si('평균(Mean)', f"{s['mean']:.3f}") +
            si('SD',         f"{s['sd']:.4f}") +
            si('RSD(%)',      f"{s['rsd']:.2f}%") +
            si('Min',         f"{s['vmin']:.2f}") +
            si('Max',         f"{s['vmax']:.2f}") +
            si('UCL',         f"{s['ucl']:.3f}", '#d97706') +
            si('LCL',         f"{s['lcl']:.3f}", '#d97706') +
            si('USL',         f"{usl:.1f}", '#059669') +
            si('LSL',         f"{lsl:.1f}", '#059669') +
            si('Cp',          f"{s['cp']:.3f}"  if s['cp']  else '—') +
            si('Cpk',         f"{s['cpk']:.3f}" if s['cpk'] else '—',
               '#059669' if s['cpk'] and s['cpk']>=1 else '#dc2626') +
            si('판정',        '적합' if s['cpk'] and s['cpk']>=1 else '부적합',
               '#059669' if s['cpk'] and s['cpk']>=1 else '#dc2626')
        )

    basis = f"{stats['n']}개 · {'Min/Max 기준' if stats['n']<5 else '2σ 기준'}" if stats else '0개'

    # 신규 결과 박스 HTML
    new_result_html = ''
    if prev:
        msg_map = {
            'Pass': '내부 기준(UCL/LCL) 및 규격(USL/LSL) 범위 내 — 정상',
            'OOT':  '내부 OOT 기준(UCL/LCL) 초과 — 추세 이탈 확인 필요',
            'OOS':  '규격(USL/LSL) 초과 — OOS 조사 및 보고 필요',
        }
        ucl_txt = f"UCL: {stats['ucl']:.3f} / LCL: {stats['lcl']:.3f} | " if stats else ''
        new_result_html = f"""
        <div class="section">
          <div class="stitle">② 신규 시험 결과</div>
          <div style="background:{sb_c.get(status,'#f3f4f6')};border:1.5px solid {sc.get(status,'#d1d5db')};
                      border-left:5px solid {sc.get(status,'#d1d5db')};border-radius:6px;padding:10px 14px;
                      display:flex;align-items:center;gap:14px;">
            <div style="font-size:28px;line-height:1">{icon.get(status,'')}</div>
            <div>
              <div style="font-size:14px;font-weight:700">
                성적번호: <span style="font-family:monospace">{prev['lot_no']}</span>
                &nbsp;&nbsp; 결과값: <span style="color:#1e3a5f;font-size:16px">{prev['value']}</span>
              </div>
              <div style="margin-top:5px;font-size:13px">
                판정: <span style="font-size:18px;font-weight:800;color:{sc.get(status,'#374151')}">{status}</span>
                &nbsp; <span style="font-size:10px;color:#6b7280">{msg_map.get(status,'')}</span>
              </div>
              <div style="font-size:9px;color:#9ca3af;margin-top:3px">
                {ucl_txt}USL: {usl} / LSL: {lsl}
              </div>
            </div>
          </div>
        </div>"""

    sec3 = "③" if prev else "②"
    sec4 = "④" if prev else "③"
    sec5 = "⑤" if prev else "④"

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>QC OOT 보고서 — {mat['name']}</title>
<style>
@page {{ size: A4 portrait; margin: 12mm 14mm 10mm; }}
*{{ box-sizing:border-box; margin:0; padding:0; }}
body{{ font-family:'Malgun Gothic','Apple SD Gothic Neo','NanumGothic',sans-serif;
       font-size:11px; color:#111827; background:#fff; }}
.header{{ display:flex; justify-content:space-between; align-items:flex-end;
          border-bottom:2.5px solid #1e3a5f; padding-bottom:8px; margin-bottom:11px; }}
.htitle{{ font-size:19px; font-weight:700; color:#1e3a5f; }}
.hsub{{ font-size:9.5px; color:#6b7280; text-align:right; line-height:1.6; }}
.section{{ margin-bottom:9px; }}
.stitle{{ font-size:11.5px; font-weight:700; color:#1e3a5f;
          border-left:3px solid #1e3a5f; padding-left:6px; margin-bottom:6px; }}
.igrid{{ display:grid; grid-template-columns:repeat(4,1fr); gap:5px; }}
.ibox{{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:4px; padding:5px 8px; }}
.ilabel{{ font-size:9px; color:#6b7280; margin-bottom:1px; }}
.ivalue{{ font-size:12px; font-weight:600; }}
.sgrid{{ display:grid; grid-template-columns:repeat(6,1fr); gap:4px; }}
.si{{ background:#f8fafc; border:1px solid #e2e8f0; border-radius:3px; padding:4px 5px; text-align:center; }}
.sl{{ font-size:8px; color:#6b7280; }}
.sv{{ font-size:11px; font-weight:600; }}
.chart-img{{ width:100%; max-height:155px; object-fit:contain; display:block; }}
table{{ width:100%; border-collapse:collapse; font-size:9.5px; }}
th{{ background:#1e3a5f; color:#fff; padding:4px 6px; text-align:center; font-size:9px; }}
td{{ padding:3px 6px; border-bottom:1px solid #f0f0f0; text-align:center; }}
.sign-wrap{{ margin-top:10px; border-top:1px solid #e2e8f0; padding-top:9px; }}
.sign-grid{{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
.sign-box{{ border:1px solid #d1d5db; border-radius:4px; padding:7px 12px; min-height:52px; position:relative; }}
.sign-label{{ font-size:10px; font-weight:600; color:#374151; }}
.sign-line{{ position:absolute; bottom:18px; left:12px; right:12px;
             border-bottom:1px solid #9ca3af; }}
.sign-name{{ position:absolute; bottom:5px; left:0; right:0;
             text-align:center; font-size:8.5px; color:#9ca3af; }}
.footer{{ margin-top:7px; text-align:center; font-size:8.5px; color:#9ca3af;
          border-top:1px solid #f0f0f0; padding-top:5px; }}
@media print{{ body{{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }} }}
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="htitle">💊 QC OOT 원료 시험 결과 보고서</div>
    <div style="font-size:10px;color:#6b7280;margin-top:2px">Out-of-Trend / Out-of-Specification Analysis Report</div>
  </div>
  <div class="hsub">
    <div><b>문서번호:</b> {doc_no}</div>
    <div><b>작성일시:</b> {now}</div>
    <div><b>작성자:</b> {current_user.get('name','—')} ({current_user.get('username','—')})</div>
  </div>
</div>

<div class="section">
  <div class="stitle">① 원료 정보</div>
  <div class="igrid">
    <div class="ibox" style="grid-column:span 2">
      <div class="ilabel">원료명 (Material Name)</div>
      <div class="ivalue" style="font-size:13px">{mat['name']}</div>
    </div>
    <div class="ibox">
      <div class="ilabel">원료코드</div>
      <div class="ivalue">{mat['code']}</div>
    </div>
    <div class="ibox">
      <div class="ilabel">데이터 수 / 통계 기준</div>
      <div class="ivalue">{basis}</div>
    </div>
  </div>
</div>

{new_result_html}

<div class="section">
  <div class="stitle">{sec3} 통계 요약</div>
  <div class="sgrid">{stat_items}</div>
</div>

<div class="section">
  <div class="stitle">{sec4} 추세 차트 (Trend Chart)</div>
  {'<img class="chart-img" src="data:image/png;base64,' + chart_b64 + '">' if chart_b64 else '<p style="color:#9ca3af;padding:8px">데이터 없음</p>'}
</div>

<div class="section">
  <div class="stitle">{sec5} 시험 이력 ({len(results)}건)</div>
  <table>
    <thead><tr><th>No.</th><th>성적번호</th><th>결과값</th><th>판정</th></tr></thead>
    <tbody>{data_rows}</tbody>
  </table>
</div>

<div class="sign-wrap">
  <div class="stitle">서명 (Signature)</div>
  <div class="sign-grid">
    <div class="sign-box">
      <div class="sign-label">시험원 &nbsp; Analyst</div>
      <div class="sign-line"></div>
      <div class="sign-name">성명 &nbsp;/&nbsp; 서명 &nbsp;/&nbsp; 날짜</div>
    </div>
    <div class="sign-box">
      <div class="sign-label">검토자 &nbsp; Reviewer</div>
      <div class="sign-line"></div>
      <div class="sign-name">성명 &nbsp;/&nbsp; 서명 &nbsp;/&nbsp; 날짜</div>
    </div>
  </div>
</div>

<div class="footer">
  QC OOT 관리 시스템 &nbsp;|&nbsp; 이 문서는 시스템에서 자동 생성되었습니다. &nbsp;|&nbsp; {doc_no}
</div>

</body>
</html>"""
    return html


# ═══════════════════════════════════════════════════════════════
#  PAGE: Login
# ═══════════════════════════════════════════════════════════════
def page_login():
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.markdown("""
        <div style='text-align:center; padding:30px 0 16px'>
          <div style='font-size:54px'>💊</div>
          <h2 style='color:#1e3a5f; margin:8px 0 4px'>QC OOT 관리 시스템</h2>
          <p style='color:#6b7280; font-size:13px'>원료 시험 결과 추세 분석 및 OOT / OOS 판정</p>
        </div>
        """, unsafe_allow_html=True)

        with st.form("login_form"):
            username = st.text_input("아이디", placeholder="아이디 입력")
            password = st.text_input("비밀번호", type="password", placeholder="비밀번호 입력")
            ok = st.form_submit_button("로그인", use_container_width=True, type="primary")

        if ok:
            if not username or not password:
                st.error("아이디와 비밀번호를 입력하세요.")
            else:
                with st.spinner("인증 중..."):
                    user = authenticate(username, password)
                if user:
                    st.session_state.user       = user
                    st.session_state.logged_in  = True
                    st.session_state.preview    = None
                    log_audit("로그인", "로그인 성공")
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 올바르지 않습니다.")

# ═══════════════════════════════════════════════════════════════
#  PAGE: Analysis
# ═══════════════════════════════════════════════════════════════
def page_analysis():
    user = st.session_state.user

    materials = get_materials()
    if not materials:
        st.warning("등록된 원료가 없습니다.")
        return

    # ── 원료 선택 + Spec 설정 ──────────────────────────────────
    sel_col, spec_col = st.columns([3, 1])
    with sel_col:
        options = {f"{m['code']} — {m['name']}": m for m in materials}
        label   = st.selectbox("**원료 선택**", list(options.keys()))
        mat     = options[label]

    with spec_col:
        if user['role'] == 'admin':
            if st.button("⚙️ Spec(USL/LSL) 설정", use_container_width=True):
                st.session_state.show_spec = True

    # ── Spec 모달 (expander) ───────────────────────────────────
    if st.session_state.get('show_spec') and user['role'] == 'admin':
        with st.expander("📐 Spec 설정", expanded=True):
            s1, s2, s3 = st.columns([1, 1, 1])
            with s1:
                new_usl = st.number_input("상한 규격 (USL)",
                    value=float(mat['usl']), step=0.1, format="%.2f", key="spec_usl")
            with s2:
                new_lsl = st.number_input("하한 규격 (LSL)",
                    value=float(mat['lsl']), step=0.1, format="%.2f", key="spec_lsl")
            with s3:
                st.write("")
                st.write("")
                if st.button("💾 저장", key="save_spec"):
                    if new_lsl >= new_usl:
                        st.error("USL은 LSL보다 커야 합니다.")
                    else:
                        sb.table('materials').update(
                            {'usl': new_usl, 'lsl': new_lsl}
                        ).eq('code', mat['code']).execute()
                        log_audit("Spec 변경",
                            f"[{mat['code']}] USL:{mat['usl']}→{new_usl}, LSL:{mat['lsl']}→{new_lsl}")
                        st.success("저장 완료")
                        st.session_state.show_spec = False
                        st.rerun()
                if st.button("닫기", key="close_spec"):
                    st.session_state.show_spec = False
                    st.rerun()

    # ── 데이터 로드 ────────────────────────────────────────────
    results = get_results(mat['code'])
    values  = [r['value'] for r in results]
    usl, lsl = float(mat['usl']), float(mat['lsl'])
    stats   = calc_stats(values, usl, lsl)

    # ═══════════════════════════════════════════════════════════
    left, right = st.columns([1, 2.2])

    # ── 왼쪽: 통계 + 데이터 테이블 ───────────────────────────
    with left:
        st.markdown("#### 📊 통계 요약")
        basis = f"{len(results)}개 · {'Min/Max 기준 (5개 미만)' if len(results) < 5 else '2σ 기준'}"
        st.caption(basis)

        if stats:
            s = stats
            rows = [
                ("평균 (Mean)",    f"{s['mean']:.3f}",  None),
                ("표준편차 (SD)",  f"{s['sd']:.4f}",    None),
                ("RSD (%)",        f"{s['rsd']:.2f} %", None),
                ("최솟값 (Min)",   f"{s['vmin']:.2f}",  None),
                ("최댓값 (Max)",   f"{s['vmax']:.2f}",  None),
                ("UCL",            f"{s['ucl']:.3f}",   "#d97706"),
                ("LCL",            f"{s['lcl']:.3f}",   "#d97706"),
                ("USL",            f"{usl:.1f}",         "#059669"),
                ("LSL",            f"{lsl:.1f}",         "#059669"),
                ("Cp",             f"{s['cp']:.3f}"  if s['cp']  else "—", None),
                ("Cpk",            f"{s['cpk']:.3f}" if s['cpk'] else "—",
                 "#059669" if s['cpk'] and s['cpk'] >= 1 else "#dc2626"),
            ]
            for lbl, val, color in rows:
                c_style = f"color:{color};font-weight:700;" if color else "font-weight:600;"
                st.markdown(
                    f"<div class='stat-box'>"
                    f"<span style='color:#6b7280'>{lbl}</span>"
                    f"<span style='{c_style}'>{val}</span>"
                    f"</div>", unsafe_allow_html=True)
            if s['cpk'] is not None:
                cpk_label = "✅ 적합" if s['cpk'] >= 1 else "❌ 부적합"
                cpk_color = "#059669" if s['cpk'] >= 1 else "#dc2626"
                st.markdown(
                    f"<div style='text-align:center;margin-top:6px;"
                    f"color:{cpk_color};font-weight:700;font-size:13px'>{cpk_label}</div>",
                    unsafe_allow_html=True)
        else:
            st.info("데이터를 입력하면 통계가 표시됩니다.")

        st.divider()

        # 데이터 테이블
        st.markdown(f"#### 📋 시험 데이터 &nbsp;<small style='color:#9ca3af;font-weight:400'>({len(results)}/15)</small>",
                    unsafe_allow_html=True)

        if results:
            df_tbl = pd.DataFrame([{
                'No': i+1,
                '성적번호': r['lot_no'],
                '값': r['value'],
                '판정': get_status(r['value'], stats, usl, lsl) if stats else "—"
            } for i, r in enumerate(results)])

            def color_status(val):
                m = {'Pass': 'color: #059669; font-weight:700',
                     'OOT':  'color: #d97706; font-weight:700',
                     'OOS':  'color: #dc2626; font-weight:700'}
                return m.get(val, '')

            styled = df_tbl.style.map(color_status, subset=['판정'])
            st.dataframe(styled, height=260, use_container_width=True, hide_index=True)

            # 관리자 편집
            if user['role'] == 'admin':
                with st.expander("🔧 데이터 수정 / 삭제 (관리자)", expanded=False):
                    sel_lot = st.selectbox("성적번호 선택",
                                           [r['lot_no'] for r in results], key="edit_lot_sel")
                    sel_r   = next((r for r in results if r['lot_no'] == sel_lot), None)
                    if sel_r:
                        ec1, ec2 = st.columns(2)
                        with ec1:
                            new_lot_e = st.text_input("성적번호", value=sel_r['lot_no'], key="edit_lot_no")
                        with ec2:
                            new_val_e = st.number_input("값", value=float(sel_r['value']),
                                                        step=0.01, key="edit_val_e")
                        bc1, bc2 = st.columns(2)
                        with bc1:
                            if st.button("💾 수정 저장", key="edit_save"):
                                sb.table('test_results').update({
                                    'lot_no': new_lot_e, 'value': new_val_e
                                }).eq('id', sel_r['id']).execute()
                                log_audit("데이터 수정",
                                    f"[{mat['code']}] {sel_lot} → {new_lot_e}({new_val_e})")
                                st.success("수정 완료")
                                st.rerun()
                        with bc2:
                            if st.button("🗑️ 삭제", key="edit_del"):
                                sb.table('test_results').delete().eq('id', sel_r['id']).execute()
                                log_audit("데이터 삭제",
                                    f"[{mat['code']}] LOT:{sel_lot} 삭제")
                                st.success("삭제 완료")
                                st.rerun()
        else:
            st.info("아직 데이터가 없습니다.")

    # ── 오른쪽: 입력 + 차트 ───────────────────────────────────
    with right:
        st.markdown("#### 🔬 신규 시험 결과 입력")

        ic1, ic2, ic3, ic4, ic5 = st.columns([1.5, 1.2, 0.9, 1.1, 0.9])
        with ic1:
            new_lot = st.text_input("성적번호 (6자리+I)", placeholder="190123I", key="new_lot_in")
        with ic2:
            new_val = st.number_input("시험 결괏값", step=0.01, format="%.2f", key="new_val_in")
        with ic3:
            st.write(""); st.write("")
            preview_btn = st.button("📈 추세 확인", use_container_width=True, key="preview_btn")
        with ic4:
            st.write(""); st.write("")
            update_btn = st.button("✅ 최종결과 업데이트",
                                   use_container_width=True, type="primary",
                                   key="update_btn",
                                   disabled=st.session_state.get('preview') is None)
        with ic5:
            st.write(""); st.write("")
            report_btn = st.button("🖨️ 레포트 출력", use_container_width=True, key="report_btn")

        # 입력 검증 & 미리보기
        if preview_btn:
            lot_in = new_lot.strip().upper()
            err = None
            if not re.match(r'^\d{6}I$', lot_in):
                err = "성적번호 형식이 올바르지 않습니다. (예: 190123I — 숫자 6자리 + I)"
            elif any(r['lot_no'].upper() == lot_in for r in results):
                err = "이미 존재하는 성적번호입니다."
            if err:
                st.error(err)
                st.session_state.preview = None
            else:
                status = get_status(float(new_val), stats, usl, lsl)
                st.session_state.preview = {
                    'lot_no': lot_in,
                    'value':  float(new_val),
                    'status': status
                }

        # 미리보기 결과 박스
        prev = st.session_state.get('preview')
        if prev:
            bg    = {'Pass':'#f0fdf4', 'OOT':'#fffbeb', 'OOS':'#fef2f2'}.get(prev['status'], '#f9fafb')
            bdr   = {'Pass':'#86efac', 'OOT':'#fde68a', 'OOS':'#fca5a5'}.get(prev['status'], '#e5e7eb')
            icon  = {'Pass':'✅', 'OOT':'⚠️', 'OOS':'🚨'}.get(prev['status'], 'ℹ️')
            msg   = {
                'Pass': '내부 기준(UCL/LCL) 및 규격(USL/LSL) 범위 내 — 정상',
                'OOT':  '내부 OOT 기준(UCL/LCL) 초과 — 추세 이탈 확인 필요',
                'OOS':  '규격(USL/LSL) 초과 — OOS 조사 및 보고 필요',
                '데이터 부족': '데이터가 부족하여 판정할 수 없습니다.',
            }.get(prev['status'], '')
            ucl_lbl = f"UCL: {stats['ucl']:.3f} / LCL: {stats['lcl']:.3f} | " if stats else ""
            st.markdown(f"""
            <div style='background:{bg}; border:1px solid {bdr}; border-left:4px solid {bdr};
                        border-radius:10px; padding:13px 16px; margin:8px 0;'>
              <b style='font-size:14px'>{icon}&nbsp; LOT: <code>{prev['lot_no']}</code>
                 &nbsp;—&nbsp; 결과값: <b>{prev['value']}</b></b><br>
              <span style='font-size:13px'>판정: <b>{prev['status']}</b></span>
              &nbsp; <small style='color:#6b7280'>{msg}</small><br>
              <small style='color:#9ca3af'>{ucl_lbl}USL: {usl} / LSL: {lsl}</small>
            </div>
            """, unsafe_allow_html=True)

            if st.button("❌ 취소", key="cancel_prev"):
                st.session_state.preview = None
                st.rerun()

        # 레포트 출력
        if report_btn:
            with st.spinner("레포트 생성 중..."):
                try:
                    html_report = build_report_html(
                        mat, results, stats,
                        st.session_state.get('preview'),
                        st.session_state.user
                    )
                    fname = f"QC_Report_{mat['code']}_{datetime.now().strftime('%Y%m%d_%H%M')}.html"
                    st.download_button(
                        label="📥 레포트 다운로드 (HTML)",
                        data=html_report.encode('utf-8'),
                        file_name=fname,
                        mime="text/html",
                        key="dl_report"
                    )
                    st.info("💡 다운로드 후 파일을 브라우저로 열고 Ctrl+P 로 인쇄하세요.")
                except Exception as e:
                    st.error(f"레포트 생성 오류: {e}")

        # 최종 업데이트 처리
        if update_btn and prev:
            # 새 항목 추가 후 정렬
            new_list = results + [{'lot_no': prev['lot_no'],
                                    'value': prev['value'],
                                    'material_code': mat['code']}]
            new_list.sort(key=lambda x: parse_lot(x['lot_no']))

            # FIFO: 15개 초과 시 가장 오래된 것 삭제
            if len(new_list) > 15:
                to_del = new_list[:len(new_list) - 15]
                for r in to_del:
                    if 'id' in r:
                        sb.table('test_results').delete().eq('id', r['id']).execute()

            # 신규 데이터 삽입
            sb.table('test_results').insert({
                'material_code': mat['code'],
                'lot_no':        prev['lot_no'],
                'value':         prev['value'],
                'created_at':    datetime.now().isoformat()
            }).execute()

            log_audit("데이터 업데이트",
                f"[{mat['code']}] {mat['name']} | LOT:{prev['lot_no']}, 값:{prev['value']}, 판정:{prev['status']}")

            st.session_state.preview = None
            st.success(f"✅ LOT {prev['lot_no']} 업데이트 완료!")
            st.rerun()

        # ── 추세 차트 ──────────────────────────────────────────
        st.markdown("#### 📉 추세 차트")

        chart_data = [{'lot_no': r['lot_no'], 'value': r['value'], 'new': False} for r in results]
        if prev:
            chart_data.append({'lot_no': prev['lot_no'], 'value': prev['value'], 'new': True})

        if chart_data:
            fig = go.Figure()

            # 기준선
            if stats:
                for y, color, dash, lbl in [
                    (stats['ucl'],  '#f59e0b', 'dash', f"UCL {stats['ucl']:.2f}"),
                    (stats['lcl'],  '#f59e0b', 'dash', f"LCL {stats['lcl']:.2f}"),
                    (stats['mean'], '#3b82f6', 'dot',  f"Mean {stats['mean']:.2f}"),
                ]:
                    fig.add_hline(y=y, line_color=color, line_dash=dash,
                                  annotation_text=lbl, annotation_position="top right",
                                  annotation_font_size=10, annotation_font_color=color)
            for y, color, dash, lbl in [
                (usl, '#10b981', 'dashdot', f"USL {usl}"),
                (lsl, '#10b981', 'dashdot', f"LSL {lsl}"),
            ]:
                fig.add_hline(y=y, line_color=color, line_dash=dash,
                              annotation_text=lbl, annotation_position="bottom right",
                              annotation_font_size=10, annotation_font_color=color)

            # 기존 데이터 선
            existing = [d for d in chart_data if not d['new']]
            if existing:
                xs = [d['lot_no'] for d in existing]
                ys = [d['value']  for d in existing]
                dot_colors = [
                    {'Pass':'#10b981','OOT':'#f59e0b','OOS':'#ef4444'}.get(
                        get_status(v, stats, usl, lsl) if stats else 'Pass', '#6b7280')
                    for v in ys
                ]
                fig.add_trace(go.Scatter(
                    x=xs, y=ys, mode='lines+markers',
                    line=dict(color='#3b82f6', width=2),
                    marker=dict(size=9, color=dot_colors,
                                line=dict(width=1.5, color='white')),
                    name='시험 결과',
                    hovertemplate='LOT: %{x}<br>값: %{y}<extra></extra>'
                ))

            # 신규 입력 (★)
            new_pts = [d for d in chart_data if d['new']]
            if new_pts:
                np_st  = get_status(new_pts[0]['value'], stats, usl, lsl) if stats else 'Pass'
                np_clr = {'Pass':'#10b981','OOT':'#f59e0b','OOS':'#ef4444'}.get(np_st, '#6b7280')
                fig.add_trace(go.Scatter(
                    x=[new_pts[0]['lot_no']], y=[new_pts[0]['value']],
                    mode='markers',
                    marker=dict(symbol='star', size=18, color=np_clr,
                                line=dict(width=2, color='#1d4ed8')),
                    name='★ 신규 입력값 (미저장)',
                    hovertemplate=f"★ {new_pts[0]['lot_no']}<br>값: {new_pts[0]['value']}<extra></extra>"
                ))

            # 범례 색상 안내용 더미 트레이스
            for clr, lbl in [('#10b981','Pass'), ('#f59e0b','OOT'), ('#ef4444','OOS')]:
                fig.add_trace(go.Scatter(
                    x=[None], y=[None], mode='markers',
                    marker=dict(size=9, color=clr),
                    name=lbl, showlegend=True
                ))

            fig.update_layout(
                height=310,
                margin=dict(l=10, r=10, t=10, b=10),
                plot_bgcolor='#fafafa',
                paper_bgcolor='white',
                xaxis=dict(tickangle=-35, tickfont=dict(size=9)),
                yaxis=dict(tickfont=dict(size=10)),
                legend=dict(orientation='h', yanchor='bottom', y=1.01,
                            xanchor='right', x=1, font=dict(size=10)),
                hovermode='x unified'
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("데이터를 입력하면 차트가 표시됩니다.")

# ═══════════════════════════════════════════════════════════════
#  PAGE: User Management
# ═══════════════════════════════════════════════════════════════
def page_users():
    if st.session_state.user['role'] != 'admin':
        st.error("관리자 권한이 필요합니다.")
        return

    st.markdown("### 👥 사용자 관리")

    # 검색
    sc1, sc2 = st.columns([1.5, 3])
    with sc1:
        sf = st.selectbox("검색 기준", ["전체","아이디","이름","권한"],
                          label_visibility="collapsed", key="u_sf")
    with sc2:
        sq = st.text_input("검색어", placeholder="검색...",
                           label_visibility="collapsed", key="u_sq")

    users = get_users()
    me    = st.session_state.user

    if sq.strip():
        q = sq.lower()
        if sf == "아이디":
            users = [u for u in users if q in u['username'].lower()]
        elif sf == "이름":
            users = [u for u in users if q in u['name'].lower()]
        elif sf == "권한":
            users = [u for u in users if
                     q in u['role'] or
                     (q in "관리자" and u['role']=='admin') or
                     (q in "사용자" and u['role']=='user')]
        else:
            users = [u for u in users if
                     q in u['username'].lower() or q in u['name'].lower()]

    # 헤더
    hc = st.columns([1.8, 1.8, 1.2, 0.8, 0.8, 0.8])
    for col, txt in zip(hc, ["아이디","이름","권한","수정","비밀번호","삭제"]):
        col.markdown(f"<small style='color:#9ca3af;font-weight:600'>{txt}</small>",
                     unsafe_allow_html=True)
    st.divider()

    for u in users:
        cols = st.columns([1.8, 1.8, 1.2, 0.8, 0.8, 0.8])
        cols[0].write(f"**{u['username']}**")
        cols[1].write(u['name'])
        role_lbl = "🔐 관리자" if u['role']=='admin' else "👤 사용자"
        cols[2].write(role_lbl)
        if cols[3].button("✏️ 수정",   key=f"ue_{u['id']}"):
            st.session_state.editing_user   = u
        if cols[4].button("🔑 초기화", key=f"ur_{u['id']}"):
            st.session_state.resetting_user = u
        if u['id'] != me['id']:
            if cols[5].button("🗑️ 삭제", key=f"ud_{u['id']}"):
                sb.table('users').delete().eq('id', u['id']).execute()
                log_audit("사용자 삭제", f"아이디:{u['username']}")
                st.success(f"{u['name']} 삭제 완료")
                st.rerun()

    st.divider()

    # ── 수정 폼 ─────────────────────────────────────────────
    if 'editing_user' in st.session_state and st.session_state.editing_user:
        eu = st.session_state.editing_user
        st.markdown(f"#### ✏️ 사용자 수정: {eu['username']}")
        with st.form("edit_user_form"):
            r1, r2, r3 = st.columns(3)
            with r1: new_un   = st.text_input("아이디", value=eu['username'])
            with r2: new_name = st.text_input("이름",   value=eu['name'])
            with r3:
                new_role = st.selectbox("권한", ["user","admin"],
                    index=0 if eu['role']=='user' else 1,
                    format_func=lambda x: "사용자" if x=='user' else "관리자")
            c1, c2, _ = st.columns([1,1,4])
            with c1: save   = st.form_submit_button("저장", type="primary")
            with c2: cancel = st.form_submit_button("취소")
        if save:
            sb.table('users').update(
                {'username': new_un, 'name': new_name, 'role': new_role}
            ).eq('id', eu['id']).execute()
            log_audit("사용자 수정", f"아이디:{new_un}, 이름:{new_name}, 권한:{new_role}")
            del st.session_state.editing_user
            st.success("수정 완료")
            st.rerun()
        if cancel:
            del st.session_state.editing_user
            st.rerun()

    # ── 비밀번호 초기화 폼 ────────────────────────────────────
    if 'resetting_user' in st.session_state and st.session_state.resetting_user:
        ru = st.session_state.resetting_user
        st.markdown(f"#### 🔑 비밀번호 초기화: {ru['name']} ({ru['username']})")
        with st.form("reset_pw_form"):
            new_pw = st.text_input("새 비밀번호 (4자 이상)", type="password")
            c1, c2, _ = st.columns([1,1,4])
            with c1: save   = st.form_submit_button("초기화", type="primary")
            with c2: cancel = st.form_submit_button("취소")
        if save:
            if len(new_pw) < 4:
                st.error("4자 이상 입력하세요.")
            else:
                sb.table('users').update(
                    {'password_hash': hash_pw(new_pw)}
                ).eq('id', ru['id']).execute()
                log_audit("비밀번호 초기화", f"아이디:{ru['username']}")
                del st.session_state.resetting_user
                st.success("초기화 완료")
                st.rerun()
        if cancel:
            del st.session_state.resetting_user
            st.rerun()

    # ── 사용자 추가 ───────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### ➕ 사용자 추가")
    with st.form("add_user_form"):
        a1, a2, a3, a4 = st.columns(4)
        with a1: add_un   = st.text_input("아이디")
        with a2: add_name = st.text_input("이름")
        with a3: add_pw   = st.text_input("초기 비밀번호", type="password")
        with a4:
            add_role = st.selectbox("권한", ["user","admin"],
                format_func=lambda x: "사용자" if x=='user' else "관리자")
        submitted = st.form_submit_button("추가", type="primary")

    if submitted:
        if not add_un or not add_name or not add_pw:
            st.error("모든 필드를 입력하세요.")
        elif len(add_pw) < 4:
            st.error("비밀번호는 4자 이상이어야 합니다.")
        else:
            exists = sb.table('users').select('id').eq('username', add_un).execute().data
            if exists:
                st.error("이미 존재하는 아이디입니다.")
            else:
                sb.table('users').insert({
                    'username': add_un, 'name': add_name,
                    'password_hash': hash_pw(add_pw), 'role': add_role,
                    'created_at': datetime.now().isoformat()
                }).execute()
                log_audit("사용자 추가", f"아이디:{add_un}, 이름:{add_name}, 권한:{add_role}")
                st.success(f"{add_name} 추가 완료!")
                st.rerun()

# ═══════════════════════════════════════════════════════════════
#  PAGE: Audit Trail
# ═══════════════════════════════════════════════════════════════
def page_audit():
    if st.session_state.user['role'] != 'admin':
        st.error("관리자 권한이 필요합니다.")
        return

    st.markdown("### 📋 Audit Trail")

    fc1, fc2, fc3, fc4, fc5 = st.columns([1.3, 1.3, 1.7, 1.7, 0.8])
    with fc1: d_from = st.date_input("날짜 시작", value=None, key="af")
    with fc2: d_to   = st.date_input("날짜 종료",  value=None, key="at")
    with fc3: u_flt  = st.text_input("사용자", placeholder="아이디 / 이름 검색",
                                     label_visibility="collapsed", key="au")
    with fc4: a_flt  = st.text_input("작업",   placeholder="작업 유형 검색",
                                     label_visibility="collapsed", key="aa")
    with fc5:
        st.write(""); st.write("")
        if st.button("초기화", key="a_reset"):
            for k in ("af","at","au","aa"):
                if k in st.session_state: del st.session_state[k]
            st.rerun()

    # Supabase 조회
    query = sb.table('audit_trail').select('*').order('created_at', desc=True).limit(2000)
    if d_from:
        query = query.gte('created_at', d_from.isoformat())
    if d_to:
        query = query.lte('created_at', (d_to + timedelta(days=1)).isoformat())
    rows = query.execute().data

    if u_flt.strip():
        q = u_flt.lower()
        rows = [r for r in rows if q in r['user_id'].lower() or q in r['user_name'].lower()]
    if a_flt.strip():
        rows = [r for r in rows if a_flt in r['action']]

    st.caption(f"총 **{len(rows)}** 건")

    if rows:
        df = pd.DataFrame(rows)[['created_at','user_name','user_id','action','detail']]
        df['created_at'] = pd.to_datetime(df['created_at']).dt.strftime('%Y-%m-%d %H:%M:%S')
        df.columns = ['일시','이름','아이디','작업','상세 내용']
        df.index   = range(1, len(df)+1)
        st.dataframe(df, height=520, use_container_width=True)
    else:
        st.info("해당 조건의 기록이 없습니다.")

# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════
def main():
    if not st.session_state.get('logged_in'):
        page_login()
        return

    user = st.session_state.user

    # ── 상단 헤더 ─────────────────────────────────────────────
    st.markdown(f"""
    <div class='header-box'>
      <span style='font-size:22px'>💊</span>
      <span style='font-size:17px; font-weight:700; margin-left:8px'>QC OOT 관리 시스템</span>
      <span style='font-size:12px; color:#93c5fd; margin-left:14px'>원료 시험 결과 추세 분석</span>
    </div>
    """, unsafe_allow_html=True)

    # ── 사이드바: 사용자 정보 + 로그아웃 ─────────────────────
    with st.sidebar:
        st.markdown(f"""
        <div style='text-align:center; padding:18px 0 10px'>
          <div style='font-size:40px'>👤</div>
          <div style='font-weight:700; font-size:16px; margin-top:6px'>{user['name']}</div>
          <div style='font-size:12px; color:#6b7280'>{user['username']}</div>
          <div style='display:inline-block; margin-top:6px;
               background:{"#ede9fe" if user["role"]=="admin" else "#dbeafe"};
               color:{"#5b21b6" if user["role"]=="admin" else "#1e40af"};
               padding:2px 14px; border-radius:10px; font-size:12px; font-weight:600'>
            {"🔐 관리자" if user["role"]=="admin" else "👤 사용자"}
          </div>
        </div>
        """, unsafe_allow_html=True)

        st.divider()

        if st.button("🚪 로그아웃", use_container_width=True):
            log_audit("로그아웃", "로그아웃")
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    # ── 탭 네비게이션 ─────────────────────────────────────────
    if user['role'] == 'admin':
        tabs = st.tabs(["📊 원료 분석", "👥 사용자 관리", "📋 Audit Trail"])
        with tabs[0]: page_analysis()
        with tabs[1]: page_users()
        with tabs[2]: page_audit()
    else:
        page_analysis()

if __name__ == "__main__":
    main()
