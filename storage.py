import json
import threading
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import gspread
from google.oauth2.service_account import Credentials
from core import fold, digest, validate, validate_plan
from hana import fold_hana, validate_hana

HEADER = ['event_id', 'timestamp', 'type', 'payload']

class KeyFormatError(ValueError):
    pass

class SheetFormatError(ValueError):
    pass

class LedgerDataError(ValueError):
    pass

def service_account_info(raw):
    info = dict(raw)
    key = str(info.get('private_key', '')).strip()
    key = key.replace('\\r\\n', '\n').replace('\\n', '\n').replace('\r\n', '\n')
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey
    try:
        parsed = load_pem_private_key(key.encode(), password=None)
        if not isinstance(parsed, RSAPrivateKey):
            raise ValueError()
    except (ValueError, TypeError) as error:
        raise KeyFormatError('서비스 계정 키 내용이 올바르지 않습니다.') from error
    info['private_key'] = key.rstrip() + '\n'
    return info

def clean_rows(rows):
    cleaned = []
    for row in rows:
        row = list(row)
        while len(row) > 4 and not row[-1].strip():
            row.pop()
        cleaned.append(row)
    if cleaned:
        cleaned[0] = [cell.strip().lstrip('\ufeff') for cell in cleaned[0]]
    return cleaned

class GoogleStore:
    def __init__(self, config):
        creds = Credentials.from_service_account_info(service_account_info(config['gcp_service_account']), scopes=['https://www.googleapis.com/auth/spreadsheets'])
        sheet_id = str(config['spreadsheet_id']).strip()
        if '/spreadsheets/d/' in sheet_id:
            sheet_id = sheet_id.split('/spreadsheets/d/', 1)[1].split('/', 1)[0]
        client = gspread.authorize(creds)
        client.set_timeout((10, 30))
        self.book = client.open_by_key(sheet_id)
        self.lock = threading.RLock()
        try:
            self.sheet = self.book.worksheet('ledger_events_v1')
        except gspread.WorksheetNotFound:
            self.sheet = self.book.add_worksheet('ledger_events_v1', rows=2000, cols=4)
        existing = clean_rows(self.sheet.get_all_values())
        if not existing:
            self.sheet.append_row(HEADER, value_input_option='RAW')
        elif existing[0] != HEADER:
            raise SheetFormatError('ledger_events_v1 탭의 형식이 다릅니다. 연결을 중단했습니다.')

    def load(self):
        records, plan, hana_records, revision = self.load_details()
        return records, plan, revision

    def load_details(self):
        rows = clean_rows(self.sheet.get_all_values())
        if not rows or rows[0] != HEADER:
            raise SheetFormatError('저장 탭의 제목 행을 확인해주세요.')
        events = [r for r in rows[1:] if any(r)]
        try:
            records, plan = fold(events)
            hana_records = fold_hana(events)
            today = datetime.now(ZoneInfo('Asia/Seoul')).date()
            for record in records + hana_records:
                if record['date'] > today.isoformat():
                    raise ValueError('미래 날짜의 실제 상환 내역이 있습니다.')
        except (ValueError, KeyError, TypeError) as error:
            raise LedgerDataError('저장된 상환 내역 형식을 확인해주세요.') from error
        return records, plan, hana_records, digest(events)

    def mutate(self, kind, data, expected, today):
        # 같은 앱 프로세스의 여러 브라우저에서 발생하는 동시 저장을 직렬화
        with self.lock:
            records, plan, hana_records, revision = self.load_details()
            if revision != expected:
                raise ValueError('다른 화면에서 내역이 변경되었습니다. 새로고침 후 다시 저장해주세요.')
            if kind == 'save':
                validate(data, records, today)
            elif kind == 'delete':
                if data['id'] not in {r['id'] for r in records}:
                    raise ValueError('이미 삭제된 내역입니다.')
            elif kind == 'plan':
                validate_plan(data)
            elif kind == 'hana_save':
                validate_hana(data, hana_records, today)
            elif kind == 'hana_delete':
                if data['id'] not in {r['id'] for r in hana_records}:
                    raise ValueError('이미 삭제된 하나은행 내역입니다.')
            else:
                raise ValueError('지원하지 않는 작업입니다.')
            self._append(kind, data)

    def undo_save(self, kind, saved, previous, expected, today):
        with self.lock:
            records, plan, hana_records, revision = self.load_details()
            if revision != expected:
                raise ValueError('내역이 변경되었습니다. 새로고침 후 취소해주세요.')
            if kind not in ('save', 'hana_save'):
                raise ValueError('취소할 저장 유형을 확인해주세요.')
            target = records if kind == 'save' else hana_records
            current = next((record for record in target if record['id'] == saved['id']), None)
            if current != saved:
                raise ValueError('저장 이후 해당 내역이 수정 또는 삭제되어 바로 취소할 수 없습니다.')
            if previous is None:
                self._append('delete' if kind == 'save' else 'hana_delete', {'id':saved['id']})
            else:
                if previous['id'] != saved['id']:
                    raise ValueError('취소할 내역의 식별 정보가 다릅니다.')
                if kind == 'save':
                    validate(previous, records, today)
                else:
                    validate_hana(previous, hana_records, today, allow_legacy=True)
                self._append(kind, previous)

    def _append(self, kind, data):
        eid = str(uuid.uuid4())
        event = [eid, datetime.now(timezone.utc).isoformat(), kind, json.dumps(data, ensure_ascii=False)]
        try:
            self.sheet.append_row(event, value_input_option='RAW')
        except Exception:
            # 응답 유실 때 성공한 저장을 재실행하지 않음
            if eid not in self.sheet.col_values(1):
                raise
