"""금액 버튼, 상환 대상 선택, 최근 기록 불러오기에 사용하는 UI 도우미."""
import streamlit as st

PEOPLE = ['엄마만', '본인만', '함께']

def person_for(record):
    mother = record.get('mother',0) + record.get('mother_interest',0)
    me = record.get('me',0) + record.get('me_interest',0)
    return '엄마만' if mother and not me else '본인만' if me and not mother else '함께'

def choose_person(prefix, initial=None):
    initial=initial or {}
    return st.radio('누구 몫을 갚나요?', PEOPLE, index=PEOPLE.index(person_for(initial)), horizontal=True, key=prefix+'_person')

def last_record(records):
    return max(records, key=lambda r:(r['date'],r['id'])) if records else None

def transfer_inputs(prefix,label,records,initial=None):
    previous=initial if initial else last_record(records) or {}
    bank_default=previous.get('bank','') if initial else previous.get('bank',st.secrets.get('bank_name',''))
    sender_default=previous.get('sender','') if initial else previous.get('sender',st.secrets.get('sender_name',''))
    a,b=st.columns(2)
    bank=a.text_input(label+' 송금·출금 은행',value=bank_default,placeholder='실제로 돈을 보낸 은행',key=prefix+'_bank')
    sender=b.text_input(label+' 실제 송금자명',value=sender_default,placeholder='이체 내역에 표시된 이름',key=prefix+'_sender')
    st.caption('대출받은 곳과 별개로 실제 돈을 보낸 은행 또는 상환금이 출금된 은행을 입력하세요. 다음 입력에는 최근 값을 채웁니다.')
    return bank.strip(),sender.strip()

def repeat_button(prefix, records, today, limits, bank=False):
    records=[r for r in records if not bank or 'mother' in r]
    last=last_record(records)
    def repeat():
        st.session_state[prefix+'_date']=today
        clipped=False
        for person in ('mother','me'):
            value=min(last[person],limits[person])
            clipped |= value != last[person]
            st.session_state[prefix+'_'+person]=value
        st.session_state[prefix+'_person']=person_for(last)
        st.session_state[prefix+'_memo']=last['memo']
        if bank:
            for field in ('bank','sender'):
                st.session_state[prefix+'_'+field]=last.get(field,'')
            for field in ('mother_interest','me_interest'):
                st.session_state[prefix+'_'+field]=last.get(field,0)
            st.session_state[prefix+'_actual']=last['fee_basis']=='actual' and not clipped
            st.session_state[prefix+'_fee']=last['fee']
        else:
            for field in ('bank','sender','interest'):
                st.session_state[prefix+'_'+field]=last[field]
            st.session_state[prefix+'_compare']=False
        st.session_state[prefix+'_repeat_note']='남은 원금에 맞춰 상환액을 줄여 불러왔습니다. 금액을 확인해주세요.' if clipped else '지난 내용을 불러왔습니다. 날짜는 오늘입니다. 이자·수수료와 금액을 확인한 뒤 저장하세요.'
    st.button('지난번과 동일하게',key=prefix+'_repeat',on_click=repeat,disabled=last is None)
    if note:=st.session_state.pop(prefix+'_repeat_note',None):
        st.info(note)

def amount_buttons(container, key, maximum):
    def change(delta):
        current=int(st.session_state.get(key,0))
        st.session_state[key]=0 if delta is None else min(maximum,current+delta)
    a,b,c=container.columns(3)
    a.button('+10만',key=key+'_plus100k',on_click=change,args=(100_000,),width='stretch')
    b.button('+100만',key=key+'_plus1m',on_click=change,args=(1_000_000,),width='stretch')
    c.button('초기화',key=key+'_reset',on_click=change,args=(None,),width='stretch')
