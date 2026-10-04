"""여자친구에게 빌린 본인 대출. 실제 이자 납부와 월 이자 예상은 별개다."""
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
import json
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from core import MAX_AMOUNT

GF_PRINCIPAL=20_000_000
GF_RATE=Decimal('0.03')

def gf_interest(principal):
    return int((Decimal(principal)*GF_RATE/12).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def gf_balance(records):
    return GF_PRINCIPAL-sum(r['principal'] for r in records)

def validate_gf(record,records,today):
    if not isinstance(record,dict) or set(record)!={'id','date','principal','interest','memo'}:
        raise ValueError('여자친구 상환 내역의 항목을 확인해주세요.')
    for key in ('id','date','memo'):
        if not isinstance(record[key],str) or ILLEGAL_CHARACTERS_RE.search(record[key]):
            raise ValueError('글이나 특수문자를 확인해주세요.')
    if not record['id'].strip() or len(record['id'])>100 or len(record['memo'])>1000:
        raise ValueError('식별 정보나 메모 길이를 확인해주세요.')
    when=date.fromisoformat(record['date'])
    if when.isoformat()!=record['date'] or when>today:
        raise ValueError('상환일은 오늘까지의 실제 날짜로 입력해주세요.')
    for key in ('principal','interest'):
        if type(record[key]) is not int or not 0<=record[key]<=MAX_AMOUNT:
            raise ValueError('금액은 0 이상의 정수로 입력해주세요.')
    total=record['principal']+record['interest']
    if not 0<total<=MAX_AMOUNT:
        raise ValueError('갚은 원금 또는 실제 납부한 이자를 입력해주세요.')
    if record['principal']>gf_balance([r for r in records if r['id']!=record['id']]):
        raise ValueError('여자친구 대출의 남은 원금보다 많이 갚을 수 없습니다.')

def fold_gf(events):
    records,seen={},set()
    for eid,timestamp,kind,raw in events:
        if eid in seen: continue
        seen.add(eid)
        if kind=='gf_save':
            data=json.loads(raw)
            validate_gf(data,[],date.max)
            records[data['id']]=data
        elif kind=='gf_delete':
            data=json.loads(raw)
            if not isinstance(data,dict) or not isinstance(data.get('id'),str) or not data['id']:
                raise ValueError('삭제할 여자친구 상환 내역을 확인해주세요.')
            records.pop(data['id'],None)
    result=sorted(records.values(),key=lambda r:(r['date'],r['id']))
    if gf_balance(result)<0:
        raise ValueError('여자친구 대출의 상환 원금 합계가 2천만 원을 초과합니다.')
    return result

def gf_excel(records):
    wb=Workbook(); summary=wb.active; summary.title='여자친구 대출 요약'
    left=gf_balance(records)
    for row in [('항목','금액/값'),('빌린 원금',GF_PRINCIPAL),('갚은 원금',GF_PRINCIPAL-left),('남은 원금',left),('연 이자율','3%'),('예상 월 이자',gf_interest(left)),('월 이자 감소액',gf_interest(GF_PRINCIPAL)-gf_interest(left)),('실제 납부 이자 합계',sum(r['interest'] for r in records)),('계산 기준','남은 원금 × 연 3% ÷ 12. 월 단위 예상치이며 일할 정산액은 별도 확인.')]:
        summary.append(row)
    sheet=wb.create_sheet('여자친구 상환 내역')
    sheet.append(['기록 ID','상환일','갚은 원금','실제 납부 이자','총 납부액','상환 후 잔액','상환 후 예상 월 이자','메모'])
    balance=GF_PRINCIPAL
    for r in records:
        balance-=r['principal']
        sheet.append([r['id'],r['date'],r['principal'],r['interest'],r['principal']+r['interest'],balance,gf_interest(balance),r['memo']])
    for sheet in wb:
        sheet.freeze_panes='A2'; sheet.auto_filter.ref=sheet.dimensions
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width=26
            for cell in column:
                if isinstance(cell.value,str): cell.data_type='s'
                if isinstance(cell.value,int): cell.number_format='#,##0'
    out=BytesIO(); wb.save(out); return out.getvalue()
