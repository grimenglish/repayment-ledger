import uuid
from datetime import date
import pandas as pd
import streamlit as st
from core import amount_words, MAX_AMOUNT
from hana import HANA_PRINCIPAL, HANA_SHARES, hana_balance, hana_balances, hana_unallocated, monthly_interest, repayment_fee, hana_excel

def render_hana(records, today, mutate, gauge, amount_input):
    left = hana_balance(records)
    remaining=hana_balances(records)
    unallocated=hana_unallocated(records)
    st.subheader('하나은행 대출')
    st.caption('엄마 2,000만 원 / 본인 5,000만 원 · 연 4.6% · 상환수수료율 0.49% · 실제 출금 계좌는 본인 계좌입니다.')
    if unallocated:
        gauge('하나은행 전체',left,HANA_PRINCIPAL,'#009b8d')
        st.warning('이전 하나은행 내역에 엄마·본인 배분이 없습니다. 내역 · 수정 탭에서 각 내역의 배분을 저장하면 개인별 잔액과 이자가 표시됩니다.')
    else:
        for col,person,label,original,color in zip(st.columns(3),['total','mother','me'],['하나은행 전체','엄마','본인'],[HANA_PRINCIPAL,HANA_SHARES['mother'],HANA_SHARES['me']],['#009b8d','#2563eb','#8b5cf6']):
            value=left if person=='total' else remaining[person]
            with col:
                gauge(label,value,original,color)
                st.metric(label+' 예상 월 이자',f'약 {monthly_interest(value):,}원')
                st.caption(f'처음보다 월 이자 약 {monthly_interest(original-value):,}원 감소')
    a,b,c=st.columns(3)
    a.metric('남은 원금', f'{left:,}원')
    b.metric('현재 예상 월 이자', f'약 {monthly_interest(left):,}원')
    c.metric('처음보다 줄어든 월 이자', f'약 {monthly_interest(HANA_PRINCIPAL-left):,}원')
    st.caption('예상 월 이자 = 남은 원금 × 연 4.6% ÷ 12. 실제 청구액은 납부일·일수와 은행 계산 방식에 따라 달라집니다.')
    entry, history, simulation = st.tabs(['하나은행 상환 입력', '하나은행 내역 · 수정', '상환 미리 계산'])

    def preview(mother, me, before, total_before=None, show_split=True):
        principal=mother+me
        before_total=sum(before.values()) if total_before is None else total_before
        after=before_total-principal
        a,b=st.columns(2)
        a.metric('상환 후 남은 원금',f'{after:,}원')
        b.metric('상환 후 예상 월 이자',f'약 {monthly_interest(after):,}원')
        a.metric('이번 상환으로 줄어드는 월 이자',f'약 {monthly_interest(principal):,}원')
        b.metric('상환수수료 예상 · 0.49% 단순 계산',f'{repayment_fee(principal):,}원')
        if show_split:
            for col,person,label,amount in zip(st.columns(2),['mother','me'],['엄마','본인'],[mother,me]):
                with col:
                    st.markdown(f'**{label} 상환 후**')
                    st.write(f'남은 원금 **{before[person]-amount:,}원**')
                    st.write(f'예상 월 이자 **약 {monthly_interest(before[person]-amount):,}원**')
                    st.caption(f'이번 상환으로 월 이자 약 {monthly_interest(amount):,}원 감소 · 수수료 단순 예상 {repayment_fee(amount):,}원')
        st.caption('수수료 예상은 상환 원금 × 0.49%입니다. 잔여기간에 따른 감면·면제는 반영하지 않습니다.')
        return repayment_fee(principal)

    def form(prefix, initial=None):
        initial=initial or {}
        available={person:remaining[person]+initial.get(person,0) for person in HANA_SHARES}
        total_available=left+initial.get('principal',0)
        with st.container(border=True):
            when=st.date_input('하나은행 상환일',value=date.fromisoformat(initial['date']) if initial else today,max_value=today,key=prefix+'_date')
            if initial and 'mother' not in initial:
                st.info(f'이전 기록: 원금 {initial["principal"]:,}원, 납부 이자 {initial["interest"]:,}원. 엄마·본인 몫으로 나눠 입력해주세요.')
            a,b=st.columns(2)
            mother=amount_input(a,'엄마 하나은행 원금 상환액',initial.get('mother',0),100_000,prefix+'_mother',maximum=min(available['mother'],total_available))
            me=amount_input(b,'본인 하나은행 원금 상환액',initial.get('me',0),100_000,prefix+'_me',maximum=min(available['me'],total_available))
            principal=mother+me
            if principal>total_available:
                st.warning('엄마·본인 상환액의 합계가 전체 잔여 원금보다 큽니다.')
            estimate=preview(mother,me,available,total_before=total_available,show_split=not unallocated) if principal<=total_available else repayment_fee(principal)
            actual=st.toggle('은행에서 확인한 실제 상환수수료 입력',value=initial.get('fee_basis')=='actual',key=prefix+'_actual')
            if actual:
                fee=amount_input(st,'실제 상환수수료',initial.get('fee',estimate),1_000,prefix+'_fee')
            else:
                fee=estimate
                st.caption('실제 수수료를 입력하지 않으면 위 금액을 ‘예상 수수료’로 구분해 기록합니다.')
            a,b=st.columns(2)
            mother_interest=amount_input(a,'엄마 이자 · 실제 납부액',initial.get('mother_interest',0),10_000,prefix+'_mother_interest')
            me_interest=amount_input(b,'본인 이자 · 실제 납부액',initial.get('me_interest',0),10_000,prefix+'_me_interest')
            interest=mother_interest+me_interest
            st.caption('이번에 은행에 실제로 낸 이자만 입력하세요. 예상 월 이자는 자동 계산되므로 여기에 넣지 않아도 됩니다. 이자와 수수료는 원금에서 차감되지 않습니다.')
            total=principal+interest+fee
            st.metric('상환 원금 + 납부 이자 + 수수료'+(' · 실제 입력' if actual else ' · 수수료는 예상'),f'{total:,}원')
            st.caption(amount_words(total) if total <= MAX_AMOUNT else '금액이 너무 큽니다.')
            memo=st.text_area('하나은행 메모',value=initial.get('memo',''),key=prefix+'_memo')
            st.caption('실제로 상환한 내역만 저장하세요. 앞으로 갚을 금액은 ‘상환 미리 계산’에서 확인할 수 있습니다.')
            if st.button('하나은행 상환 저장',type='primary',key=prefix+'_save'):
                data=dict(id=initial.get('id',str(uuid.uuid4())),date=when.isoformat(),principal=int(principal),mother=int(mother),me=int(me),interest=int(interest),mother_interest=int(mother_interest),me_interest=int(me_interest),fee=int(fee),fee_basis='actual' if actual else 'estimate',memo=memo)
                if initial and 'mother' not in initial and (principal!=initial['principal'] or interest!=initial['interest']):
                    st.error('배분을 확인할 때는 이전 원금·납부 이자 합계를 유지해주세요.')
                elif not initial and any(all(r.get(k)==data[k] for k in ('date','mother','me','mother_interest','me_interest','fee','fee_basis','memo')) for r in records):
                    st.warning('동일한 하나은행 내역이 있습니다. 내역 탭에서 확인해주세요.')
                else:
                    mutate('hana_save',data)

    with entry:
        st.caption('엄마에게 받은 돈으로 갚은 원금은 ‘엄마’ 칸에, 본인 돈으로 갚은 원금은 ‘본인’ 칸에 입력하세요. 출금 계좌가 같아도 각자의 대출 잔액만 줄어듭니다.')
        if not unallocated:
            form('hana_new')
        else:
            st.info('기존 하나은행 기록의 배분을 먼저 확인해주세요. 가족 상환장부는 계속 사용할 수 있습니다.')
    with history:
        months=['전체']+sorted({r['date'][:7] for r in records},reverse=True)
        month=st.selectbox('하나은행 조회 월',months,key='hana_month')
        balance=HANA_PRINCIPAL
        rows=[]
        for record in records:
            balance-=record['principal']
            if month=='전체' or record['date'][:7]==month:
                rows.append({'상환일':record['date'],'갚은 원금':record['principal'],'실제 납부 이자':record['interest'],'상환수수료':record['fee'],'수수료 구분':'실제' if record['fee_basis']=='actual' else '예상','상환 후 잔액':balance,'상환 후 예상 월 이자':monthly_interest(balance),'월 이자 감소액':monthly_interest(record['principal']),'메모':record['memo']})
                rows[-1].update({'엄마 원금':record.get('mother','배분 확인 필요'),'본인 원금':record.get('me','배분 확인 필요'),'엄마 납부 이자':record.get('mother_interest','배분 확인 필요'),'본인 납부 이자':record.get('me_interest','배분 확인 필요')})
        if rows:
            st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
        else:
            st.info('조회할 하나은행 상환 내역이 없습니다.')
        st.download_button('하나은행 장부 엑셀 다운로드',hana_excel(records),file_name=f'하나은행_상환장부_{today.isoformat()}.xlsx',mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        if records:
            with st.expander('하나은행 내역 수정 · 삭제'):
                mapping={r['id']:r for r in records}
                chosen=st.selectbox('변경할 하나은행 내역',list(mapping),format_func=lambda i:f'{mapping[i]["date"]} / {mapping[i]["principal"]:,}원 / {i[:8]}',key='hana_edit_select')
                form('hana_edit_'+chosen,mapping[chosen])
                confirmed=st.checkbox('선택한 하나은행 내역을 삭제합니다.',key='hana_confirm_'+chosen)
                if st.button('하나은행 선택 내역 삭제',disabled=not confirmed,key='hana_delete_'+chosen):
                    mutate('hana_delete',{'id':chosen})
    with simulation:
        if not unallocated:
            a,b=st.columns(2)
            mother=amount_input(a,'엄마 미리 계산할 상환 원금',0,100_000,'hana_simulation_mother',maximum=remaining['mother'])
            me=amount_input(b,'본인 미리 계산할 상환 원금',min(10_000_000,remaining['me']),100_000,'hana_simulation_me',maximum=remaining['me'])
            preview(mother,me,remaining)
        else:
            st.info('이전 기록의 엄마·본인 배분을 확인하면 개인별 미리 계산을 사용할 수 있습니다.')
        st.caption('계산만 합니다. 이 화면에서 입력한 금액은 장부에 저장되지 않습니다.')
    with st.expander('이자와 상환수수료 계산 기준'):
        st.write('월 이자는 현재 금리가 계속 유지된다는 가정의 비교용 예상치입니다. 실제 납부한 이자는 입력한 금액만 기록합니다.')
        st.caption('원 단위 반올림으로 개인별 이자의 합계와 전체 예상 월 이자는 1원 차이가 날 수 있습니다.')
        st.write('수수료는 요청하신 0.49%를 상환 원금에 곱한 단순 예상치입니다. 은행에서 확인한 금액을 입력하면 실제 수수료로 기록됩니다.')
        st.markdown('[하나은행 공식 수수료 산식 안내](https://kebhana.com/cont/mall/mall08/mall0802/mall080204/1448202_115200.jsp): 상품에 따라 대출잔여일수 ÷ 대출기간이 추가 적용되므로 계약 조건과 실제 은행 안내 금액을 확인하세요.')
