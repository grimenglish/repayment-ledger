import json
import threading
import uuid
from datetime import datetime, timezone
import gspread
from google.oauth2.service_account import Credentials
from core import fold, digest, validate

HEADER = ['event_id', 'timestamp', 'type', 'payload']

class GoogleStore:
    def __init__(self, config):
        creds = Credentials.from_service_account_info(dict(config['gcp_service_account']), scopes=['https://www.googleapis.com/auth/spreadsheets'])
        self.book = gspread.authorize(creds).open_by_key(config['spreadsheet_id'])
        self.lock = threading.RLock()
        try:
            self.sheet = self.book.worksheet('ledger_events_v1')
        except gspread.WorksheetNotFound:
            self.sheet = self.book.add_worksheet('ledger_events_v1', rows=2000, cols=4)
        existing = self.sheet.get_all_values()
        if not existing:
            self.sheet.append_row(HEADER, value_input_option='RAW')
        elif existing[0] != HEADER:
            raise ValueError('ledger_events_v1 탭의 형식이 다릅니다. 연결을 중단했습니다.')

    def load(self):
        rows = self.sheet.get_all_values()
        if not rows or rows[0] != HEADER:
            raise ValueError('저장 탭의 제목 행을 확인해주세요.')
        events = [r for r in rows[1:] if any(r)]
        records, plan = fold(events)
        return records, plan, digest(events)

    def mutate(self, kind, data, expected, today):
        # 같은 앱 프로세스의 여러 브라우저에서 발생하는 동시 저장을 직렬화
        with self.lock:
            records, plan, revision = self.load()
            if revision != expected:
                raise ValueError('다른 화면에서 내역이 변경되었습니다. 새로고침 후 다시 저장해주세요.')
            if kind == 'save':
                validate(data, records, today)
            elif kind == 'delete':
                if data['id'] not in {r['id'] for r in records}:
                    raise ValueError('이미 삭제된 내역입니다.')
            elif kind == 'plan':
                if set(data) != {'mother', 'me'} or any(type(v) is not int or v < 0 for v in data.values()):
                    raise ValueError('월 상환 목표를 확인해주세요.')
            else:
                raise ValueError('지원하지 않는 작업입니다.')
            eid = str(uuid.uuid4())
            event = [eid, datetime.now(timezone.utc).isoformat(), kind, json.dumps(data, ensure_ascii=False)]
            try:
                self.sheet.append_row(event, value_input_option='RAW')
            except Exception:
                # 응답 유실 때 성공한 저장을 재실행하지 않음
                if eid not in self.sheet.col_values(1):
                    raise
