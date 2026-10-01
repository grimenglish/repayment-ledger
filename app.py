import hashlib
import hmac
import time
import uuid
from datetime import datetime, date
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from core import PRINCIPAL, DEFAULT_PLAN, balances, month_paid, payoff, excel
from storage import GoogleStore

st.set_page_config(page_title='우리집 상환장부', page_icon='◔', layout='wide')
st.markdown('''<style>
.stApp{background:#f6f8fc} .block-container{max-width:1180px;padding-top:2rem}
h1{letter-spacing:-1.7px} [data-testid="stMetric"]{background:white;padding:18px;border:1px solid #e5eaf3;border-radius:16px}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:18px} .stButton>button{border-radius:10px}
</style>''', unsafe_allow_html=True)

def authenticate():
    try:
        mode = st.secrets.get('login_mode', 'password')
        if mode == 'google':
            allowed = str(st.secrets.get('allowed_email', '')).strip().casefold()
            if not allowed or 'auth' not in st.secrets:
                st.error('Google 로그인 설정이 필요합니다. README를 확인해주세요.')
                st.stop()
            if not st.user.is_logged_in:
                st.title('우리집 상환장부')
                st.caption('본인 Google 계정으로 로그인해주세요.')
                if st.button('Google로 로그인', type='primary'):
                    st.login('google')
                st.stop()
            if st.user.get('email', '').casefold() != allowed or st.user.get('email_verified') is not True:
                st.error('이 계정은 접근 권한이 없습니다.')
                if st.button('다른 계정으로 로그인'):
                    st.logout()
                st.stop()
            if st.sidebar.button('로그아웃'):
                st.logout()
            return
        if mode != 'password':
            st.error('로그인 방식 설정을 확인해주세요.')
            st.stop()
        config = dict(st.secrets.get('login', {}))
    except FileNotFoundError:
        st.error('먼저 Secrets에 로그인 설정을 넣어주세요. README에 예시가 있습니다.')
        st.stop()
    if not config.get('password_hash') or not config.get('salt'):
        st.error('비밀번호 설정이 없습니다. 로그인 설정 후 사용할 수 있습니다.')
        st.stop()
    if st.session_state.get('authenticated_until', 0) > time.time():
        if st.sidebar.button('로그아웃'):
            st.session_state.clear()
            st.rerun()
        return
    st.title('우리집 상환장부')
    st.caption('비밀번호를 입력하면 개인 장부가 열립니다.')
    with st.form('login'):
        password = st.text_input('비밀번호', type='password')
        submitted = st.form_submit_button('로그인', type='primary')
    if submitted:
        if time.time() < st.session_state.get('locked_until', 0):
            st.error('잠시 후 다시 시도해주세요.')
        else:
            candidate = hashlib.pbkdf2_hmac('sha256', password.encode(), config['salt'].encode(), 600_000).hex()
            if hmac.compare_digest(candidate, str(config['password_hash'])):
                st.session_state['authenticated_until'] = time.time() + 3600 * 8
                st.session_state['failures'] = 0
                st.rerun()
            else:
                failures = st.session_state.get('failures', 0) + 1
                st.session_state['failures'] = failures
                st.session_state['locked_until'] = time.time() + min(60, failures * 2)
                st.error('비밀번호를 확인해주세요.')
    st.stop()

authenticate()  # 데이터 연결과 조회보다 먼저 실행

@st.cache_resource
def connect():
    return GoogleStore(st.secrets)

st.title('우리집 상환장부')
st.caption('친척에게 빌린 2억 원 · 엄마 1억 / 본인 1억 · 실제 송금 계좌는 본인 계좌')
try:
    store = connect()
    records, plan, revision = store.load()
except Exception as error:
    st.error('Google Sheets 연결에 실패했습니다. 아래 점검 결과를 확인해주세요.')
    error_type = type(error).__name__
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    st.code('오류 유형: ' + error_type + (f' / HTTP {status}' if isinstance(status, int) else ''))
    hints = {
        'SpreadsheetNotFound': '시트 ID 또는 서비스 계정의 시트 공유 권한을 확인해주세요.',
        'PermissionError': '시트 편집자 권한과 Google Sheets API 사용 설정을 확인해주세요.',
        'MalformedError': '서비스 계정의 필수 설정 또는 private_key 형식을 확인해주세요.',
        'RefreshError': '서비스 계정 키의 유효성을 확인해주세요. 삭제된 키나 다른 계정의 키일 수 있습니다.',
        'ValueError': 'private_key 형식 또는 ledger_events_v1 탭의 제목 행을 확인해주세요.',
        'KeyError': 'Secrets의 spreadsheet_id와 gcp_service_account 설정을 확인해주세요.',
    }
    st.info(hints.get(error_type, 'Google 연결 설정과 API 응답 상태를 확인해주세요.'))
    account = dict(st.secrets.get('gcp_service_account', {}))
    key = str(account.get('private_key', ''))
    checks = {
        '시트 ID 입력': bool(st.secrets.get('spreadsheet_id')),
        '서비스 계정 설정 있음': bool(account),
        'project_id 입력': bool(account.get('project_id')),
        'client_email 입력': bool(account.get('client_email')),
        'token_uri 입력': bool(account.get('token_uri')),
        '키 시작 문구 정상': key.startswith('-----BEGIN PRIVATE KEY-----'),
        '키 끝 문구 정상': key.rstrip().endswith('-----END PRIVATE KEY-----'),
        '키 줄바꿈 정상': chr(10) in key and chr(92)+'n' not in key,
    }
    for label, ok in checks.items():
        st.write(('✅ ' if ok else '❌ ') + label)
    st.caption('이 화면에는 키와 로그인 보안 비밀을 표시하지 않습니다.')
    if st.button('연결 다시 시도'):
        connect.clear()
        st.rerun()
    st.stop()

today = datetime.now(ZoneInfo('Asia/Seoul')).date()
remaining, paid = balances(records), month_paid(records, today)
if any(v < 0 for v in remaining.values()):
    st.error('저장된 원금 합계가 대출액을 초과합니다. Google Sheets 원본을 확인해주세요.')
    st.stop()
if message := st.session_state.pop('notice', None):
    st.success(message)

with st.sidebar:
    st.subheader('개인 장부')
    st.caption('Google Sheets 연결됨')
    if st.button('내역 새로고침'):
        st.rerun()
    st.caption('금액 단위: 원 / 날짜 기준: 한국시간')


def gauge(label, left, original, color):
    percent = (original - left) / original * 100
    fig = go.Figure(go.Indicator(mode='gauge', value=percent, gauge={
        'axis': {'range': [0, 100], 'visible': False}, 'bar': {'color': color, 'thickness': .8},
        'bgcolor': '#eaf0f8', 'borderwidth': 0, 'shape': 'angular'}))
    fig.add_annotation(x=.5, y=.25, text=f'<b>{left:,.0f}원</b><br><span style="font-size:14px">{percent:.1f}% 상환</span>', showarrow=False, font={'size': 24, 'color': '#17233d'})
    fig.update_layout(height=210, margin={'t': 15, 'b': 0, 'l': 20, 'r': 20}, paper_bgcolor='rgba(0,0,0,0)')
    with st.container(border=True):
        st.subheader(label)
        st.caption('남은 원금')
        st.plotly_chart(fig, width="stretch", config={'displayModeBar': False})
        st.caption(f'갚은 원금 {original-left:,}원 / 빌린 원금 {original:,}원')

for col, label, left, original, color in zip(st.columns(3), ['전체', '엄마', '본인'], [sum(remaining.values()), remaining['mother'], remaining['me']], [PRINCIPAL*2, PRINCIPAL, PRINCIPAL], ['#2563eb', '#0d9488', '#8b5cf6']):
    with col:
        gauge(label, left, original, color)

st.subheader('이번 달 상환 계획')
for col, p, label in zip(st.columns(2), ['mother', 'me'], ['엄마', '본인']):
    with col:
        target = min(plan[p], remaining[p] + paid[p])
        due = min(remaining[p], max(target - paid[p], 0))
        d = payoff(remaining[p], plan[p], paid[p], today)
        with st.container(border=True):
            st.markdown(f'**{label} · 월 {plan[p]:,}원**')
            st.progress(min(paid[p]/target, 1.0) if target else 1.0)
            st.write(f'이번 달 {paid[p]:,}원 상환 · 더 갚을 금액 **{due:,}원**')
            st.caption('완납 완료' if not remaining[p] else f'예상 완납월: {d:%Y년 %m월}' if d else '예상 완납월: 월 목표 설정 필요')
ends = [payoff(remaining[p], plan[p], paid[p], today) for p in remaining]
st.caption(('전체 예상 완납월: ' + max(ends).strftime('%Y년 %m월')) if all(ends) else '전체 예상 완납월: 월 목표 설정 필요')
st.caption('이번 달 남은 목표액을 이번 달에 갚고, 다음 달부터 매월 목표액을 갚는 기준입니다. 이자는 원금을 줄이지 않습니다.')


def mutate(kind, data):
    try:
        store.mutate(kind, data, revision, today)
    except ValueError as e:
        st.error(str(e))
        return
    except Exception:
        st.error('저장 결과를 확인할 수 없습니다. 새로고침하여 내역을 확인한 뒤 다시 시도해주세요.')
        return
    st.session_state['notice'] = 'Google Sheets에 저장했습니다.'
    st.rerun()

entry, history, settings = st.tabs(['상환 기록', '내역 · 엑셀', '계획 · 선상환'])
with entry:
    st.caption('한 번 송금한 전체 금액을 입력한 뒤 엄마·본인 원금과 이자로 나눠주세요.')
    quick = st.toggle('이번 달 정기 상환액 자동 채우기')
    defaults = {p: min(remaining[p], max(plan[p]-paid[p],0)) if quick else 0 for p in remaining}
    def record_form(prefix, initial=None):
        initial = initial or {}
        with st.form(prefix):
            a,b = st.columns(2)
            when = a.date_input('상환일', value=date.fromisoformat(initial['date']) if initial else today, max_value=today)
            bank = b.text_input('송금 은행', value=initial.get('bank',''), placeholder='예: 국민은행')
            sender = st.text_input('실제 송금자명', value=initial.get('sender', st.secrets.get('sender_name','')), placeholder='본인 이름')
            a,b,c = st.columns(3)
            mother = a.number_input('엄마 원금 상환액', min_value=0, value=initial.get('mother', defaults['mother']), step=100_000)
            me = b.number_input('본인 원금 상환액', min_value=0, value=initial.get('me', defaults['me']), step=100_000)
            interest = c.number_input('이자 지급액', min_value=0, value=initial.get('interest',0), step=10_000)
            total = st.number_input('실제 총 송금액', min_value=0, value=initial.get('total',sum(defaults.values())), step=100_000)
            memo = st.text_area('메모', value=initial.get('memo',''), placeholder='예: 정기상환 / 본인 선상환')
            submitted = st.form_submit_button('확인한 금액 저장', type='primary')
        if submitted:
            record = dict(id=initial.get('id', str(uuid.uuid4())), date=when.isoformat(), bank=bank.strip(), sender=sender.strip(), total=int(total), mother=int(mother), me=int(me), interest=int(interest), memo=memo)
            if not initial and any(all(r[k] == record[k] for k in ('date','bank','sender','total','mother','me','interest','memo')) for r in records):
                st.warning('동일한 상환 내역이 있습니다. 내역 탭에서 확인해주세요.')
            else:
                mutate('save', record)
    record_form('new_quick' if quick else 'new_manual')

with history:
    months = ['전체'] + sorted({r['date'][:7] for r in records}, reverse=True)
    month = st.selectbox('조회 월', months)
    selected = [r for r in records if month == '전체' or r['date'][:7] == month]
    labels = {'date':'상환일','bank':'은행','sender':'실제 송금자','total':'총 송금액','mother':'엄마 원금','me':'본인 원금','interest':'이자','memo':'메모'}
    if selected:
        st.dataframe(pd.DataFrame(selected)[list(labels)].rename(columns=labels), hide_index=True, width="stretch")
        st.caption(f'조회 합계: 원금 {sum(r["mother"]+r["me"] for r in selected):,}원 / 이자 {sum(r["interest"] for r in selected):,}원')
    else:
        st.info('아직 기록된 상환 내역이 없습니다.')
    st.download_button('전체 장부 엑셀 다운로드', excel(records, plan, today), file_name=f'상환장부_{today.isoformat()}.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if records:
        with st.expander('내역 수정 · 삭제'):
            ids = [r['id'] for r in records]
            mapping = {r['id']:r for r in records}
            chosen = st.selectbox('변경할 내역', ids, format_func=lambda i:f'{mapping[i]["date"]} / {mapping[i]["bank"]} / {mapping[i]["total"]:,}원 / {i[:8]}')
            record_form('edit_'+chosen, mapping[chosen])
            confirm = st.checkbox('선택한 내역을 삭제합니다.', key='confirm_'+chosen)
            if st.button('선택 내역 삭제', disabled=not confirm):
                mutate('delete', {'id':chosen})
    if records:
        left = PRINCIPAL * 2
        points = []
        for r in records:
            left -= r['mother'] + r['me']
            points.append({'날짜':r['date'], '전체 잔액':left})
        st.line_chart(pd.DataFrame(points).groupby('날짜').last())
with settings:
    with st.form('plan'):
        st.subheader('월 상환 목표')
        a,b = st.columns(2)
        mother = a.number_input('엄마 월 목표', min_value=0, value=int(plan['mother']), step=100_000)
        me = b.number_input('본인 월 목표', min_value=0, value=int(plan['me']), step=100_000)
        if st.form_submit_button('목표 저장'):
            mutate('plan', {'mother':int(mother), 'me':int(me)})
    with st.expander('선상환하면 얼마나 빨라질까?'):
        person = st.selectbox('선상환 대상', ['me','mother'], format_func=lambda p:'본인' if p=='me' else '엄마')
        extra = st.number_input('추가 상환액', min_value=0, max_value=remaining[person], value=min(20_000_000,remaining[person]), step=100_000)
        before = payoff(remaining[person], plan[person], paid[person], today)
        after = payoff(remaining[person]-extra, plan[person], paid[person]+extra, today)
        if before and after:
            saved = (before.year-after.year)*12 + before.month-after.month
            st.metric('예상 완납월', after.strftime('%Y년 %m월'), f'{saved}개월 단축' if saved else '같은 월 완납')
            st.write(f'추가 상환 후 잔액: **{remaining[person]-extra:,}원**')
        else:
            st.info('월 상환 목표를 설정하면 비교할 수 있습니다.')
        st.caption('지금 추가 상환하는 가정입니다. 계산만 하며 실제 장부에는 저장하지 않습니다.')
