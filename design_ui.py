from html import escape
import inspect
import streamlit as st
from core import amount_words
from hana import monthly_interest, hana_balances, hana_unallocated

MOTHER_COLOR='#0d9488'
ME_COLOR='#2563eb'
THEME='''<style>
.stApp{background:#f5f7fb;color:#17233d}
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
@media(max-width:600px){[data-testid="stMetricValue"]{font-size:1.7rem}.block-container{padding-top:1rem}.payment-receipt{padding:18px}}
</style>'''

def person_card(person, label, left, original, family_left, bank_left):
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
        st.metric(label+' 하나은행 예상 월 이자',f'약 {monthly_interest(bank_left):,}원')
        with st.expander('대출별 잔액 보기'):
            st.write(f'가족 대출 **{family_left:,}원**')
            st.write(f'하나은행 **{bank_left:,}원**')

def main_navigation(labels):
    parameters=inspect.signature(st.tabs).parameters
    if all(key in parameters for key in ('default','key','on_change')):
        containers=st.tabs(labels,default=labels[0],key='main_navigation',on_change='rerun')
        return dict(zip(labels,containers))
    active=st.session_state.get('requested_tab',labels[0])
    ordered=[active]+[label for label in labels if label!=active] if active in labels else labels
    return dict(zip(ordered,st.tabs(ordered)))

def request_tab(label):
    st.session_state['requested_tab']=label
    # Older Streamlit versions select the requested tab by reordering labels.
    if 'key' in inspect.signature(st.tabs).parameters:
        st.session_state['main_navigation']=label

def make_receipt(kind, saved, previous, family_records, bank_records):
    if kind=='save':
        from core import balances
        before=balances(family_records)
        others=[r for r in family_records if r['id']!=saved['id']]
        after=balances(others+[saved])
        split_ready=True
        before_known=True
    else:
        before=hana_balances(bank_records)
        others=[r for r in bank_records if r['id']!=saved['id']]
        after=hana_balances(others+[saved])
        split_ready=not hana_unallocated(others+[saved])
        before_known=not hana_unallocated(bank_records)
    return {'kind':kind,'saved':dict(saved),'edited':previous is not None,'before':before,'after':after,'split_ready':split_ready,'before_known':before_known}

def render_receipt(receipt):
    record=receipt['saved']
    source='가족 대출' if receipt['kind']=='save' else '하나은행'
    parts=[]
    for person,label in [('mother','엄마'),('me','본인')]:
        if record.get(person,0): parts.append(f'{label} {record[person]:,}원')
    heading='상환 내역 수정 완료' if receipt['edited'] else (' · '.join(parts)+' 상환 완료' if parts else '납부 비용 기록 완료')
    lines=[]
    if receipt['split_ready']:
        for person,label in [('mother','엄마'),('me','본인')]:
            if record.get(person,0) or receipt['before'][person]!=receipt['after'][person]:
                line=f'{label} 남은 원금 <b>{receipt["before"][person]:,}원 → {receipt["after"][person]:,}원</b>' if receipt['before_known'] else f'{label} 남은 원금 <b>{receipt["after"][person]:,}원</b>'
                if receipt['kind']=='hana_save':
                    reduction=monthly_interest(receipt['before'][person])-monthly_interest(receipt['after'][person])
                    line+=f'<br>예상 월 이자 약 {monthly_interest(receipt["after"][person]):,}원'
                    if receipt['before_known']:
                        line+=' · '+(f'약 {reduction:,}원 감소' if reduction>=0 else f'약 {-reduction:,}원 증가')
                lines.append('<p>'+line+'</p>')
    else:
        lines.append('<p>이전 하나은행 내역의 배분을 확인하면 개인별 잔액이 확정됩니다.</p>')
    if receipt['kind']=='hana_save':
        basis='실제 입력' if record['fee_basis']=='actual' else '예상'
        lines.append(f'<p>상환수수료 {record["fee"]:,}원 · {basis}</p>')
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
                    st.write(f'상환 원금 **{record["principal"]:,}원** · 납부 이자 {record["interest"]:,}원')
                    st.write(f'수수료 {record["fee"]:,}원 · '+('실제' if record['fee_basis']=='actual' else '예상'))
                if record['memo']: st.write(record['memo'])
                def edit(identifier=record['id']):
                    st.session_state[editor_key]=identifier
                    st.session_state[open_key]=True
                st.button('이 내역 수정 · 삭제',key=key_prefix+'_edit_'+record['id'],on_click=edit)
