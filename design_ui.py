from html import escape
import inspect
import streamlit as st
from core import amount_words
from hana import monthly_interest, hana_balances, hana_unallocated,estimate_fee_rate
from girlfriend import GF_PRINCIPAL,gf_balance,gf_interest

MOTHER_COLOR='#0d9488'
ME_COLOR='#2563eb'
THEME='''<style>
.stApp{background:#f5f7fb;color:#17233d}
.overview-hero{background:linear-gradient(120deg,#12213e,#254776);border-radius:24px;padding:28px 32px;color:#fff;margin:12px 0 24px;box-shadow:0 12px 32px #17233d12}
.overview-hero .hero-kicker{color:#c4d5f1;font-size:.9rem;letter-spacing:.6px}
.overview-hero .hero-amount{font-size:2.5rem;font-weight:800;letter-spacing:-1.5px;margin:8px 0}
.overview-hero .hero-note{color:#d8e6fa;line-height:1.7}
.monthly-goal{background:#f5f8fd;border-radius:16px;padding:16px 18px;margin:12px 0}
.monthly-goal .goal-label{font-size:.85rem;color:#526177}
.monthly-goal .goal-amount{font-size:1.65rem;font-weight:750;letter-spacing:-.7px;margin:4px 0}
.st-key-overview_mother,.st-key-overview_me{background:#fff;border-radius:22px;box-shadow:0 6px 24px #17233d08}
.st-key-overview_mother{border-top:4px solid #0d9488}
.st-key-overview_me{border-top:4px solid #2563eb}
.milestone{padding:12px 16px;border-radius:12px;background:#fff6dc;color:#705214;font-weight:650;margin:12px 0 0}
.block-container{max-width:1160px;padding-top:2rem;padding-bottom:3rem}
h1{letter-spacing:-1.5px} h2,h3{letter-spacing:-.6px}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:20px;border-color:#e2e8f0;background:#fff}
[data-testid="stMetricValue"]{font-size:2rem;font-weight:750;letter-spacing:-1px}
[data-testid="stMetricLabel"]{color:#526177}
.stButton>button{border-radius:12px;min-height:44px;font-weight:600}
.stTabs [data-baseweb="tab-list"]{gap:8px;padding-bottom:8px}
.stTabs [data-baseweb="tab"]{font-weight:650;padding:10px 16px;border-radius:12px;white-space:nowrap}
.stTabs [aria-selected="true"]{background:#e8efff;color:#1d4ed8}
.st-key-overview_mother [data-testid="stProgress"] [role="progressbar"]>div>div{background:#0d9488}
.st-key-overview_me [data-testid="stProgress"] [role="progressbar"]>div>div{background:#2563eb}
.payment-receipt{padding:24px;border-radius:20px;background:#effaf5;border:1px solid #b9e5d2;margin:8px 0 16px}
.payment-receipt h2{font-size:1.65rem;margin:6px 0 12px;color:#123e2c}
.payment-receipt p{margin:6px 0;font-size:1rem;line-height:1.7}
.role-pill{display:inline-block;border-radius:10px;padding:8px 12px;margin:5px 8px 5px 0;font-weight:650}
.role-mother{background:#e7f8f4;color:#08776d}.role-me{background:#eaf0ff;color:#1d4ed8}
@media(max-width:600px){[data-testid="stMetricValue"]{font-size:1.7rem}.block-container{padding-top:1rem}.payment-receipt{padding:18px}.overview-hero{padding:22px}.overview-hero .hero-amount{font-size:2rem}}
</style>'''

def monthly_goal(left,paid,plan):
    target=min(plan,left+paid)
    due=min(left,max(target-paid,0))
    status='완납 완료' if left==0 else '월 목표 설정 필요' if plan==0 else '이번 달 목표 달성' if due==0 else '이번 달 더 갚을 금액'
    return {'target':target,'due':due,'status':status}

def request_person(person,loan,today):
    if loan=='가족 대출':
        st.session_state['family_auto_fill']=False
        st.session_state['new_manual_person']='엄마만' if person=='mother' else '본인만'
        st.session_state['new_manual_date']=today
        for field in ('mother','me','interest'):
            st.session_state['new_manual_'+field]=0
        st.session_state['new_manual_memo']=''
        st.session_state['new_manual_compare']=False
    elif loan=='하나은행 대출':
        st.session_state['hana_new_person']='엄마만' if person=='mother' else '본인만'
        st.session_state['hana_new_date']=today
        for field in ('mother','me','mother_interest','me_interest'):
            st.session_state['hana_new_'+field]=0
        st.session_state['hana_new_actual']=False
        st.session_state['hana_new_memo']=''
        request_tab('하나은행 상환 입력','hana_navigation')
    else:
        st.session_state['gf_new_date']=today
        st.session_state['gf_new_principal']=0
        st.session_state['gf_new_interest']=0
        st.session_state['gf_new_memo']=''
        request_tab('여자친구 상환 입력','gf_navigation')
    request_tab(loan)

def overview_hero(left,paid,due,today):
    st.markdown(f'<div class="overview-hero"><div class="hero-kicker">OUR FAMILY · {today:%Y.%m}</div><div class="hero-amount">남은 대출 {left:,}원</div><div class="hero-note">지금까지 {paid:,}원 상환<br>가족 대출 이번 달 남은 목표 <b>{due:,}원</b></div></div>',unsafe_allow_html=True)

def person_card(person, label, left, original, family_left, bank_left,month_paid,plan,today,gf_left=None):
    color=MOTHER_COLOR if person=='mother' else ME_COLOR
    paid=original-left
    with st.container(border=True,key='overview_'+person):
        st.markdown(f'<div style="color:{color};font-weight:750;font-size:1.2rem">{escape(label)}</div>',unsafe_allow_html=True)
        st.metric('엄마 남은 대출' if person=='mother' else '내 남은 대출',f'{left:,}원')
        st.caption(amount_words(left))
        percentage=min(max(paid/original*100,0),100)
        st.markdown(f'<div role="progressbar" aria-label="{escape(label)} 상환 진행률" aria-valuemin="0" aria-valuemax="100" aria-valuenow="{percentage:.1f}" style="background:#e2e8f0;border-radius:8px;overflow:hidden;height:16px"><div style="width:{percentage:.4f}%;height:16px;background:{color}"></div></div>',unsafe_allow_html=True)
        st.markdown(f'**지금까지 {paid:,}원 상환 · {paid/original*100:.1f}% 완료**')
        st.caption(f'처음 빌린 금액 {original:,}원')
        goal=monthly_goal(family_left,month_paid,plan)
        st.markdown(f'<div class="monthly-goal"><div class="goal-label">가족 대출 · {goal["status"]}</div><div class="goal-amount" style="color:{color}">{goal["due"]:,}원</div><div class="goal-label">이번 달 {month_paid:,}원 상환 / 목표 {goal["target"]:,}원</div></div>',unsafe_allow_html=True)
        st.caption(f'하나은행 예상 월 이자 약 {monthly_interest(bank_left):,}원')
        a,b=st.columns(2)
        a.button('가족 상환 기록',key='card_'+person+'_family',type='primary',width='stretch',on_click=request_person,args=(person,'가족 대출',today),disabled=family_left==0)
        b.button('하나은행 상환 기록',key='card_'+person+'_hana',width='stretch',on_click=request_person,args=(person,'하나은행 대출',today),disabled=bank_left==0)
        if gf_left is not None:
            st.caption(f'여자친구 대출 예상 월 이자 약 {gf_interest(gf_left):,}원')
            st.button('여자친구 상환 기록',key='card_me_gf',width='stretch',on_click=request_person,args=('me','여자친구 대출',today),disabled=gf_left==0)
        with st.expander('대출별 잔액 보기'):
            st.write(f'가족 대출 **{family_left:,}원**')
            st.write(f'하나은행 **{bank_left:,}원**')
            if gf_left is not None: st.write(f'여자친구 **{gf_left:,}원**')

def main_navigation(labels,key='main_navigation'):
    parameters=inspect.signature(st.tabs).parameters
    if all(key in parameters for key in ('default','key','on_change')):
        containers=st.tabs(labels,default=labels[0],key=key,on_change='rerun')
        return dict(zip(labels,containers))
    active=st.session_state.get('requested_tab' if key=='main_navigation' else 'requested_'+key,labels[0])
    ordered=[active]+[label for label in labels if label!=active] if active in labels else labels
    return dict(zip(ordered,st.tabs(ordered)))

def request_tab(label,key='main_navigation'):
    st.session_state['requested_tab' if key=='main_navigation' else 'requested_'+key]=label
    # Older Streamlit versions select the requested tab by reordering labels.
    if 'key' in inspect.signature(st.tabs).parameters:
        st.session_state[key]=label

def loan_name(kind):
    return {'save':'가족 대출','hana_save':'하나은행','gf_save':'여자친구 대출'}[kind]

def achievement_messages(receipt):
    if receipt['edited'] or not receipt['before_known'] or not receipt['split_ready']:
        return []
    originals={'mother':100_000_000,'me':100_000_000} if receipt['kind']=='save' else {'mother':20_000_000,'me':50_000_000} if receipt['kind']=='hana_save' else {'mother':0,'me':GF_PRINCIPAL}
    source=loan_name(receipt['kind'])
    messages=[]
    for person,label in [('mother','엄마'),('me','본인')]:
        before,after=receipt['before'][person],receipt['after'][person]
        if after>=before: continue
        original=originals[person]
        before_paid,after_paid=original-before,original-after
        if after==0:
            messages.append(f'{label} {source} 완납! 끝까지 해냈어요.')
        elif (after_paid*10//original)>(before_paid*10//original):
            messages.append(f'{label} {source} {after_paid*10//original*10}% 상환 달성! 꾸준히 나아가고 있어요.')
        elif after_paid//10_000_000>before_paid//10_000_000:
            messages.append(f'{label} {source} 누적 {after_paid//10_000_000*1_000:,}만원 상환! 한 걸음 더 가까워졌어요.')
    return messages

def make_receipt(kind, saved, previous, family_records, bank_records,gf_records=None):
    if kind=='save':
        from core import balances
        before=balances(family_records)
        others=[r for r in family_records if r['id']!=saved['id']]
        after=balances(others+[saved])
        split_ready=True
        before_known=True
    elif kind=='hana_save':
        before=hana_balances(bank_records)
        others=[r for r in bank_records if r['id']!=saved['id']]
        after=hana_balances(others+[saved])
        split_ready=not hana_unallocated(others+[saved])
        before_known=not hana_unallocated(bank_records)
    else:
        gf_records=gf_records or []
        before={'mother':0,'me':gf_balance(gf_records)}
        after={'mother':0,'me':gf_balance([r for r in gf_records if r['id']!=saved['id']]+[saved])}
        split_ready=before_known=True
    return {'kind':kind,'saved':dict(saved),'edited':previous is not None,'before':before,'after':after,'split_ready':split_ready,'before_known':before_known}

def render_receipt(receipt):
    record=receipt['saved']
    source=loan_name(receipt['kind'])
    parts=[]
    for person,label in [('mother','엄마'),('me','본인')]:
        amount=record['principal'] if receipt['kind']=='gf_save' and person=='me' else record.get(person,0)
        if amount: parts.append(f'{label} {amount:,}원')
    heading='상환 내역 수정 완료' if receipt['edited'] else (' · '.join(parts)+' 상환 완료' if parts else '납부 비용 기록 완료')
    lines=[]
    if receipt['split_ready']:
        for person,label in [('mother','엄마'),('me','본인')]:
            if record.get(person,0) or receipt['before'][person]!=receipt['after'][person]:
                line=f'{label} 남은 원금 <b>{receipt["before"][person]:,}원 → {receipt["after"][person]:,}원</b>' if receipt['before_known'] else f'{label} 남은 원금 <b>{receipt["after"][person]:,}원</b>'
                if receipt['kind'] in ('hana_save','gf_save'):
                    interest_fn=gf_interest if receipt['kind']=='gf_save' else monthly_interest
                    reduction=interest_fn(receipt['before'][person])-interest_fn(receipt['after'][person])
                    line+=f'<br>예상 월 이자 약 {interest_fn(receipt["after"][person]):,}원'
                    if receipt['before_known']:
                        line+=' · '+(f'약 {reduction:,}원 감소' if reduction>=0 else f'약 {-reduction:,}원 증가')
                lines.append('<p>'+line+'</p>')
    else:
        lines.append('<p>이전 하나은행 내역의 배분을 확인하면 개인별 잔액이 확정됩니다.</p>')
    if receipt['kind']=='hana_save':
        basis='실제 입력' if record['fee_basis']=='actual' else '예상'
        lines.append(f'<p>상환수수료 {record["fee"]:,}원 · {basis}</p>')
    for message in achievement_messages(receipt):
        lines.append(f'<div class="milestone">✦ {escape(message)}</div>')
    st.markdown(f'<div class="payment-receipt"><small>{source} · {escape(record["date"])}</small><h2>{escape(heading)}</h2>'+''.join(lines)+'</div>',unsafe_allow_html=True)
    st.caption('이 화면은 방금 저장한 결과입니다. 수정 입력은 새 상환을 추가하지 않고 기존 내역을 변경합니다.')

def history_cards(records, source, editor_key, open_key, key_prefix, bank=False):
    if not records: return
    pages=(len(records)+9)//10
    page=st.selectbox('내역 페이지',list(range(1,pages+1)),key=key_prefix+'_page',format_func=lambda value:f'{value} / {pages} 페이지') if pages>1 else 1
    subset=list(reversed(records))[(page-1)*10:page*10]
    for record in subset:
        with st.container(border=True):
            st.markdown(f'**{record["date"]} · {source}**')
            if bank and 'mother' not in record:
                st.write(f'상환 원금 **{record["principal"]:,}원** · 엄마·본인 배분 확인 필요')
            else:
                pills=''.join(f'<span class="role-pill role-{person}">{label} {record.get(person,0):,}원</span>' for person,label in [('mother','엄마'),('me','본인')] if record.get(person,0))
                if pills: st.markdown(pills,unsafe_allow_html=True)
                else: st.caption('원금 상환 없이 비용만 납부한 기록입니다.')
            with st.expander('상세 보기'):
                if not bank:
                    st.write(f'송금 은행: {record["bank"]} · 송금자: {record["sender"]}')
                    st.write(f'총 송금액 **{record["total"]:,}원** · 이자 {record["interest"]:,}원')
                else:
                    st.write(f'송금·출금 은행: {record.get("bank","") or "은행 미입력"} · 송금자: {record.get("sender","") or "송금자 미입력"}')
                    st.write(f'상환 원금 **{record["principal"]:,}원** · 납부 이자 {record["interest"]:,}원')
                    st.write(f'수수료 {record["fee"]:,}원 · '+('실제' if record['fee_basis']=='actual' else '예상'))
                    if record['fee_basis']=='estimate': st.caption('이 기록의 예상 수수료율: '+estimate_fee_rate(record))
                if record['memo']: st.write(record['memo'])
                def edit(identifier=record['id']):
                    st.session_state[editor_key]=identifier
                    st.session_state[open_key]=True
                st.button('이 내역 수정 · 삭제',key=key_prefix+'_edit_'+record['id'],on_click=edit)
