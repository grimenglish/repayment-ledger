import uuid
from datetime import date
import pandas as pd
import streamlit as st
from girlfriend import GF_PRINCIPAL,gf_balance,gf_interest,gf_excel
from design_ui import main_navigation
from easy_ui import last_record,transfer_inputs

def render_girlfriend(records,today,mutate,amount_input):
    left=gf_balance(records)
    st.subheader('여자친구 대출')
    st.caption('본인이 빌린 2,000만원 · 연 3% · 상환한 원금만큼 잔액과 예상 월 이자가 줄어듭니다.')
    with st.container(border=True):
        a,b,c=st.columns(3)
        a.metric('여자친구 대출 남은 원금',f'{left:,}원')
        b.metric('여자친구 대출 예상 월 이자',f'약 {gf_interest(left):,}원')
        c.metric('여자친구 대출 갚은 원금',f'{GF_PRINCIPAL-left:,}원')
        st.progress((GF_PRINCIPAL-left)/GF_PRINCIPAL)
    labels=['여자친구 상환 입력','여자친구 내역 · 수정','여자친구 상환 미리 계산']
    tabs=main_navigation(labels,key='gf_navigation')

    def preview(principal,before):
        after=before-principal
        with st.container(border=True):
            a,b=st.columns(2)
            a.metric('여자친구 상환 후 남은 원금',f'{after:,}원')
            b.metric('여자친구 상환 후 예상 월 이자',f'약 {gf_interest(after):,}원')
            st.markdown(f'예상 월 이자 **약 {gf_interest(before)-gf_interest(after):,}원 감소**')

    def form(prefix,initial=None):
        initial=initial or {}
        available=gf_balance([r for r in records if r['id']!=initial.get('id')])
        if not initial:
            previous=last_record(records)
            def repeat():
                st.session_state[prefix+'_date']=today
                st.session_state[prefix+'_principal']=min(previous['principal'],available)
                st.session_state[prefix+'_interest']=previous['interest']
                st.session_state[prefix+'_memo']=previous['memo']
                for field in ('bank','sender'): st.session_state[prefix+'_'+field]=previous.get(field,'')
            st.button('여자친구 지난번과 동일하게',key=prefix+'_repeat',on_click=repeat,disabled=previous is None)
        with st.container(border=True):
            when=st.date_input('여자친구 상환일',value=date.fromisoformat(initial['date']) if initial else today,max_value=today,key=prefix+'_date')
            bank,sender=transfer_inputs(prefix,'여자친구',records,initial)
            principal=amount_input(st,'여자친구 갚은 원금',initial.get('principal',0),100_000,prefix+'_principal',maximum=available,quick=True)
            def fill_all(): st.session_state[prefix+'_principal']=available
            st.button('여자친구 남은 원금 전액 채우기',key=prefix+'_all',on_click=fill_all,disabled=available==0)
            preview(principal,available)
            with st.expander('추가 입력 · 실제 납부한 이자, 메모',expanded=bool(initial.get('interest',0))):
                interest=amount_input(st,'여자친구 실제 납부 이자',initial.get('interest',0),10_000,prefix+'_interest')
                memo=st.text_area('여자친구 상환 메모',value=initial.get('memo',''),key=prefix+'_memo')
                st.caption('이자를 실제로 지급했을 때만 입력하세요. 이자는 원금을 줄이지 않습니다.')
            st.metric('여자친구 총 납부액',f'{principal+interest:,}원')
            if st.button('여자친구 상환 저장',type='primary',key=prefix+'_save'):
                data=dict(id=initial.get('id',str(uuid.uuid4())),date=when.isoformat(),principal=int(principal),interest=int(interest),memo=memo,bank=bank,sender=sender)
                if not bank:
                    st.error('실제 송금 은행을 입력해주세요.')
                elif not initial and any(all(r.get(key,'')==data[key] for key in ('date','principal','interest','memo','bank','sender')) for r in records):
                    st.warning('동일한 여자친구 상환 내역이 있습니다. 내역 탭에서 확인해주세요.')
                else:
                    mutate('gf_save',data)

    with tabs[labels[0]]:
        form('gf_new')
    with tabs[labels[1]]:
        months=['전체']+sorted({r['date'][:7] for r in records},reverse=True)
        month=st.selectbox('여자친구 조회 월',months,key='gf_month')
        selected=[r for r in records if month=='전체' or r['date'][:7]==month]
        if selected:
            pages=(len(selected)+9)//10
            page=st.selectbox('여자친구 내역 페이지',list(range(1,pages+1)),key='gf_page') if pages>1 else 1
            for r in list(reversed(selected))[(page-1)*10:page*10]:
                with st.container(border=True):
                    st.markdown(f'**{r["date"]} · 여자친구 대출**')
                    st.markdown(f'<span class="role-pill role-me">본인 {r["principal"]:,}원 상환</span>',unsafe_allow_html=True)
                    with st.expander('여자친구 상세 보기'):
                        st.write(f'송금 은행: {r.get("bank","") or "은행 미입력"} · 송금자: {r.get("sender","") or "송금자 미입력"}')
                        st.write(f'실제 납부 이자 {r["interest"]:,}원 · 총 납부액 {r["principal"]+r["interest"]:,}원')
                        if r['memo']: st.write(r['memo'])
                        def edit(identifier=r['id']):
                            st.session_state['gf_edit_selection']=identifier
                            st.session_state['open_gf_editor']=True
                        st.button('여자친구 이 내역 수정 · 삭제',key='gf_history_edit_'+r['id'],on_click=edit)
            with st.expander('표로 여자친구 전체 내역 보기'):
                table=pd.DataFrame(selected)[['date','principal','interest','memo']].rename(columns={'date':'상환일','principal':'갚은 원금','interest':'실제 납부 이자','memo':'메모'})
                st.dataframe(table,hide_index=True,width='stretch')
        else:
            st.info('조회할 여자친구 상환 기록이 없습니다.')
        st.download_button('여자친구 장부 엑셀 다운로드',gf_excel(records),file_name=f'여자친구_상환장부_{today.isoformat()}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',key='gf_excel')
        if records:
            with st.expander('여자친구 내역 수정 · 삭제',expanded=st.session_state.pop('open_gf_editor',False)):
                mapping={r['id']:r for r in records}
                chosen=st.selectbox('변경할 여자친구 내역',list(mapping),format_func=lambda i:f'{mapping[i]["date"]} / {mapping[i]["principal"]:,}원 / {i[:8]}',key='gf_edit_selection')
                form('gf_edit_'+chosen,mapping[chosen])
                confirm=st.checkbox('선택한 여자친구 내역을 삭제합니다.',key='gf_confirm_'+chosen)
                if st.button('여자친구 선택 내역 삭제',key='gf_delete_'+chosen,disabled=not confirm):
                    mutate('gf_delete',{'id':chosen})
    with tabs[labels[2]]:
        principal=amount_input(st,'여자친구 미리 계산할 상환 원금',0,100_000,'gf_simulation',maximum=left,quick=True)
        preview(principal,left)
        st.caption('계산만 합니다. 입력한 금액은 저장되지 않습니다.')
    st.caption('월 이자 = 남은 원금 × 연 3% ÷ 12. 처음 월 이자는 5만원입니다. 상환월의 실제 이자 정산은 날짜와 합의한 계산 기준에 따라 별도로 확인하세요.')
