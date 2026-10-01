import hashlib
import hmac
import time
import uuid
from datetime import datetime, date
from zoneinfo import ZoneInfo
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from core import PRINCIPAL, DEFAULT_PLAN, MAX_AMOUNT, amount_words, balances, month_paid, payoff, excel
from storage import GoogleStore
from hana_ui import render_hana
from hana import hana_balance, hana_balances, hana_unallocated, monthly_interest
from easy_ui import choose_person, repeat_button, amount_buttons, last_record
from backup import backup_excel
from design_ui import THEME, MOTHER_COLOR, ME_COLOR, person_card, main_navigation, request_tab, make_receipt, render_receipt, history_cards

st.set_page_config(page_title='우리집 상환장부', page_icon='◔', layout='wide')
st.markdown(THEME,unsafe_allow_html=True)

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
st.caption('가족 상환장부 · 하나은행 대출을 탭별로 관리합니다.')
try:
    store = connect()
    records, plan, hana_records, revision, backup_status = store.load_details(include_backup=True)
except Exception as error:
    st.error('Google Sheets 연결에 실패했습니다. 아래 점검 결과를 확인해주세요.')
    error_type = type(error).__name__
    status = getattr(getattr(error, 'response', None), 'status_code', None)
    st.code('오류 유형: ' + error_type + (f' / HTTP {status}' if isinstance(status, int) else ''))
    hints = {
        'KeyFormatError': 'private_key 내용이 손상되었거나 일부가 빠졌습니다. 다운로드한 서비스 계정 JSON 파일의 private_key 값을 처음부터 끝까지 다시 복사해 Streamlit Secrets에 넣어주세요.',
        'SheetFormatError': 'ledger_events_v1 탭의 A1~D1을 event_id / timestamp / type / payload로 맞춰주세요. 기존 상환 내역은 지우지 마세요.',
        'LedgerDataError': '시트에 저장된 내역 형식이 올바르지 않습니다. ledger_events_v1 탭의 화면을 확인해주세요.',
        'Timeout': 'Google 응답이 지연되었습니다. 잠시 후 연결 다시 시도를 눌러주세요.',
        'ReadTimeout': 'Google 응답이 지연되었습니다. 잠시 후 연결 다시 시도를 눌러주세요.',
        'ConnectTimeout': 'Google 연결이 지연되었습니다. 잠시 후 연결 다시 시도를 눌러주세요.',
        'ConnectionError': 'Google에 연결할 수 없습니다. 잠시 후 연결 다시 시도를 눌러주세요.',
        'APIError': 'Google Sheets API 요청이 실패했습니다. HTTP 403이면 API 사용 설정·편집 권한, 429이면 잠시 후 다시 시도를 확인해주세요.',
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



def mutate(kind, data, message='Google Sheets에 저장했습니다.'):
    target=records if kind=='save' else hana_records
    previous=next((r for r in target if r['id']==data.get('id')),None) if kind in ('save','hana_save') else None
    try:
        store.mutate(kind, data, revision, today)
    except ValueError as e:
        st.error(str(e))
        return
    except Exception:
        st.error('저장 결과를 확인할 수 없습니다. 새로고침하여 내역을 확인한 뒤 다시 시도해주세요.')
        return
    st.session_state['notice'] = message
    if kind=='backup_confirm':
        st.session_state.pop('backup_downloaded',None)
    if kind in ('save','hana_save'):
        st.session_state['last_save']={'kind':kind,'saved':dict(data),'previous':dict(previous) if previous else None}
        st.session_state['payment_receipt']=make_receipt(kind,data,previous,records,hana_records)
    st.rerun()

def amount_input(container, label, value, step, key, maximum=MAX_AMOUNT, quick=False):
    amount = container.number_input(label, min_value=0, max_value=maximum, value=value, step=step, key=key)
    container.caption(f'{amount:,}원 · {amount_words(amount)}')
    if quick:
        amount_buttons(container,key,maximum)
    return amount

if receipt:=st.session_state.pop('payment_receipt',None):
    render_receipt(receipt)

if backup_status['overdue']:
    st.warning('상환장부 백업 시기가 되었습니다. 전체 장부를 엑셀로 내려받아 보관해주세요.')
with st.expander('전체 장부 엑셀 백업',expanded=backup_status['overdue'] or bool(st.session_state.get('backup_downloaded'))):
    if backup_status['last']:
        st.caption(f'최근 백업 완료: {backup_status["last"]:%Y-%m-%d} · 다음 안내: {backup_status["due"]:%Y-%m-%d}')
    elif backup_status['due']:
        st.caption(f'백업 완료 기록이 없습니다. 연간 백업 안내 예정일: {backup_status["due"]:%Y-%m-%d}')
    else:
        st.caption('상환 기록이 생기면 1년 뒤부터 백업을 안내합니다.')
    st.write('가족·하나은행 장부와 원본 이력을 한 파일에 담습니다. 다운로드 후 파일을 열어 기록을 확인하고 PC와 다른 저장 위치에 함께 보관하세요.')
    if st.download_button('전체 장부 백업 엑셀 다운로드',backup_excel(records,plan,hana_records,backup_status['events'],today,revision),file_name=f'우리집_상환장부_전체백업_{today.isoformat()}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='download_full_backup',on_click='rerun'):
        st.session_state['backup_downloaded']={'revision':revision,'date':today.isoformat()}
    if downloaded:=st.session_state.get('backup_downloaded'):
        if downloaded != {'revision':revision,'date':today.isoformat()}:
            st.info('기록이 변경되었거나 날짜가 지났습니다. 최신 파일을 다시 다운로드해주세요.')
        elif st.button('백업 파일 저장 완료',key='confirm_full_backup'):
            mutate('backup_confirm',downloaded,'백업 완료 날짜를 저장했습니다. 1년 후 다시 안내합니다.')
    st.caption('파일 다운로드만으로 백업 완료를 표시하지 않습니다. 실제 저장과 확인을 마친 뒤 완료 버튼을 누르세요.')

if pending:=st.session_state.get('last_save'):
    source='가족 대출' if pending['kind']=='save' else '하나은행'
    amount=pending['saved'].get('total',pending['saved'].get('principal',0))
    st.caption(f'최근 저장: {source} · {pending["saved"]["date"]} · {amount:,}원')
    if st.button('방금 저장 취소',key='undo_last_save'):
        try:
            store.undo_save(pending['kind'],pending['saved'],pending['previous'],revision,today)
        except ValueError as error:
            st.error(str(error))
        except Exception:
            st.error('취소 결과를 확인할 수 없습니다. 새로고침 후 내역을 확인해주세요.')
        else:
            st.session_state.pop('last_save',None)
            st.session_state['notice']='방금 저장을 취소했습니다.'
            st.rerun()

tabs=main_navigation(['전체 현황', '가족 대출', '가족 내역 · 엑셀', '가족 계획 · 선상환', '하나은행 대출'])
overview,entry,history,settings,hana_tab=(tabs[label] for label in ['전체 현황','가족 대출','가족 내역 · 엑셀','가족 계획 · 선상환','하나은행 대출'])
with overview:
    st.subheader('얼마나 갚았을까요?')
    bank_remaining=hana_balances(hana_records)
    if not hana_unallocated(hana_records):
        a,b=st.columns(2)
        with a:
            person_card('mother','엄마',remaining['mother']+bank_remaining['mother'],120_000_000,remaining['mother'],bank_remaining['mother'])
        with b:
            person_card('me','본인',remaining['me']+bank_remaining['me'],150_000_000,remaining['me'],bank_remaining['me'])
    else:
        a,b,c=st.columns(3)
        a.metric('가족 대출 잔액',f'{sum(remaining.values()):,}원')
        b.metric('하나은행 잔액',f'{hana_balance(hana_records):,}원')
        c.metric('하나은행 예상 월 이자',f'약 {monthly_interest(hana_balance(hana_records)):,}원')
        st.info('이전 하나은행 내역의 배분을 확인하면 엄마·본인 총 잔액이 표시됩니다.')
    st.caption(f'우리집 전체 잔액 {sum(remaining.values())+hana_balance(hana_records):,}원 · 하나은행 예상 월 이자 약 {monthly_interest(hana_balance(hana_records)):,}원')
    with st.container(border=True):
        st.subheader('오늘 갚은 돈을 기록하세요')
        loan=st.radio('갚을 대출',['가족 대출','하나은행 대출'],horizontal=True,key='start_repayment_loan')
        st.button('상환 기록하기',type='primary',width='stretch',key='start_repayment',on_click=request_tab,args=(loan,))
        st.caption('대출 선택 → 엄마·본인 선택 → 금액 입력. 날짜는 오늘로 채워집니다.')
with entry:
    for col, label, left, original, color in zip(st.columns(3), ['전체', '엄마', '본인'], [sum(remaining.values()), remaining['mother'], remaining['me']], [PRINCIPAL*2, PRINCIPAL, PRINCIPAL], ['#334155', MOTHER_COLOR, ME_COLOR]):
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

    st.caption('엄마·본인이 갚은 원금과 이자를 입력하세요. 송금액은 자동으로 더합니다. 금액 입력 후 Enter를 누르거나 다른 칸을 클릭하면 한글 금액이 표시됩니다.')
    quick = st.toggle('이번 달 정기 상환액 자동 채우기')
    defaults = {p: min(remaining[p], max(plan[p]-paid[p],0)) if quick else 0 for p in remaining}
    def record_form(prefix, initial=None):
        initial = initial or {}
        latest=last_record(records) or {}
        available=balances([r for r in records if r['id']!=initial.get('id')])
        if not initial:
            repeat_button(prefix,records,today,available)
        with st.container(border=True):
            person=choose_person(prefix,initial)
            when = st.date_input('상환일', value=date.fromisoformat(initial['date']) if initial else today, max_value=today, key=prefix+'_date')
            a,b=st.columns(2) if person=='함께' else (st,st)
            mother = amount_input(a, '엄마 원금 상환액', min(initial.get('mother', defaults['mother']),available['mother']), 100_000, prefix+'_mother',maximum=available['mother'],quick=True) if person!='본인만' else 0
            me = amount_input(b, '본인 원금 상환액', min(initial.get('me', defaults['me']),available['me']), 100_000, prefix+'_me',maximum=available['me'],quick=True) if person!='엄마만' else 0
            bank_default=initial.get('bank',latest.get('bank',st.secrets.get('bank_name','신한은행')))
            sender_default=initial.get('sender',latest.get('sender',st.secrets.get('sender_name','')))
            with st.expander('추가 입력 · 은행, 송금자, 이자, 메모',expanded=not sender_default):
                bank = st.text_input('송금 은행', value=bank_default, placeholder='예: 국민은행', key=prefix+'_bank')
                sender = st.text_input('실제 송금자명', value=sender_default, placeholder='본인 이름', key=prefix+'_sender')
                interest = amount_input(st, '이자 지급액', initial.get('interest',0), 10_000, prefix+'_interest')
                st.caption('이자가 없으면 0원입니다. 이자는 남은 원금에서 빠지지 않습니다.')
                memo = st.text_area('메모', value=initial.get('memo',''), placeholder='예: 정기상환 / 본인 선상환', key=prefix+'_memo')
            combined = mother + me + interest
            st.metric('저장할 송금액 · 자동 합산', f'{combined:,}원')
            st.caption(amount_words(combined) if combined <= MAX_AMOUNT else '금액이 너무 큽니다.')
            st.caption(f'엄마 {mother:,}원 + 본인 {me:,}원 + 이자 {interest:,}원')
            total = combined
            if st.toggle('은행에서 보낸 금액을 따로 입력해 비교', key=prefix+'_compare'):
                total = amount_input(st, '실제 총 송금액', min(initial.get('total', combined), MAX_AMOUNT), 100_000, prefix+'_total')
                if total != combined:
                    st.warning(f'입력한 송금액 {total:,}원과 합산 금액 {combined:,}원이 다릅니다. 차이 {abs(total-combined):,}원을 확인해주세요.')
            with st.container(border=True):
                st.markdown('**저장 전 확인**')
                st.write(f'엄마 {mother:,}원 · 본인 {me:,}원 상환')
                st.write(f'엄마 잔액 {available["mother"]:,}원 → **{available["mother"]-mother:,}원**')
                st.write(f'본인 잔액 {available["me"]:,}원 → **{available["me"]-me:,}원**')
            st.caption('은행에서 실제로 보낸 금액과 위 금액이 같은지 확인한 뒤 저장하세요.')
            submitted = st.button('확인한 금액 저장', type='primary', key=prefix+'_save')
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
        history_cards(selected,'가족 대출','family_edit_selection','open_family_editor','family_history')
        with st.expander('표로 전체 내역 보기'):
            st.dataframe(pd.DataFrame(selected)[list(labels)].rename(columns=labels), hide_index=True, width="stretch")
        st.caption(f'조회 합계: 원금 {sum(r["mother"]+r["me"] for r in selected):,}원 / 이자 {sum(r["interest"] for r in selected):,}원')
    else:
        st.info('아직 기록된 상환 내역이 없습니다.')
    st.download_button('가족 장부 엑셀 다운로드', excel(records, plan, today), file_name=f'상환장부_{today.isoformat()}.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    if records:
        with st.expander('내역 수정 · 삭제',expanded=st.session_state.pop('open_family_editor',False)):
            ids = [r['id'] for r in records]
            mapping = {r['id']:r for r in records}
            chosen = st.selectbox('변경할 내역', ids, format_func=lambda i:f'{mapping[i]["date"]} / {mapping[i]["bank"]} / {mapping[i]["total"]:,}원 / {i[:8]}',key='family_edit_selection')
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
    with st.container(border=True):
        st.subheader('월 상환 목표')
        a,b = st.columns(2)
        mother = amount_input(a, '엄마 월 목표', int(plan['mother']), 100_000, 'plan_mother')
        me = amount_input(b, '본인 월 목표', int(plan['me']), 100_000, 'plan_me')
        if st.button('목표 저장'):
            mutate('plan', {'mother':int(mother), 'me':int(me)})
    with st.expander('선상환하면 얼마나 빨라질까?'):
        person = st.selectbox('선상환 대상', ['me','mother'], format_func=lambda p:'본인' if p=='me' else '엄마')
        extra = amount_input(st, '추가 상환액', min(20_000_000,remaining[person]), 100_000, 'extra_'+person, maximum=remaining[person])
        before = payoff(remaining[person], plan[person], paid[person], today)
        after = payoff(remaining[person]-extra, plan[person], paid[person]+extra, today)
        if before and after:
            saved = (before.year-after.year)*12 + before.month-after.month
            st.metric('예상 완납월', after.strftime('%Y년 %m월'), f'{saved}개월 단축' if saved else '같은 월 완납')
            st.write(f'추가 상환 후 잔액: **{remaining[person]-extra:,}원**')
        else:
            st.info('월 상환 목표를 설정하면 비교할 수 있습니다.')
        st.caption('지금 추가 상환하는 가정입니다. 계산만 하며 실제 장부에는 저장하지 않습니다.')

with hana_tab:
    render_hana(hana_records, today, mutate, gauge, amount_input)
