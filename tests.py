import unittest
import json
import time
import threading
from datetime import date
from io import BytesIO
from unittest.mock import patch, MagicMock
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest
from core import *
from storage import GoogleStore, HEADER, service_account_info, clean_rows, KeyFormatError, LedgerDataError, SheetFormatError
TODAY=date(2026,10,1)
def record(**kw):
    r=dict(id='a',date='2026-10-01',bank='국민',sender='본인',total=5_000_000,mother=4_000_000,me=1_000_000,interest=0,memo='')
    r.update(kw)
    return r
class Sheet:
    def __init__(self): self.rows=[HEADER.copy()]
    def get_all_values(self): return [r.copy() for r in self.rows]
    def append_row(self,row,**kw): self.rows.append(row)
    def col_values(self,col): return [r[col-1] for r in self.rows]
def fake_store():
    s=GoogleStore.__new__(GoogleStore); s.sheet=Sheet(); s.lock=threading.RLock(); return s
class Tests(unittest.TestCase):
    def test_google_login_blocks_other_accounts(self):
        import streamlit as st
        class User(dict):
            is_logged_in=True
        for email,verified in [('other@example.com',True),('me@example.com',False)]:
            st.cache_resource.clear()
            with patch('streamlit.user',User(email=email,email_verified=verified)), patch('storage.GoogleStore') as connection:
                app=AppTest.from_file('app.py')
                app.secrets['login_mode']='google'
                app.secrets['allowed_email']='me@example.com'
                app.secrets['auth']={'google':{}}
                app.run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                connection.assert_not_called()

    def test_google_login_allows_verified_owner(self):
        import streamlit as st
        class User(dict):
            is_logged_in=True
        st.cache_resource.clear()
        with patch('streamlit.user',User(email='ME@example.com',email_verified=True)), patch('storage.GoogleStore',return_value=fake_store()) as connection:
            app=AppTest.from_file('app.py')
            app.secrets['login_mode']='google'
            app.secrets['allowed_email']='me@example.com'
            app.secrets['auth']={'google':{}}
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.tabs),3)
            connection.assert_called_once()

    def test_paid_dashboard_with_zero_plan(self):
        import streamlit as st
        st.cache_resource.clear()
        s=fake_store()
        s.mutate('save',record(mother=100_000_000,me=100_000_000,total=200_000_000),s.load()[2],TODAY)
        s.mutate('plan',{'mother':0,'me':0},s.load()[2],TODAY)
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get('plotly_chart')),3)
            self.assertEqual(len(app.dataframe),1)

    def test_invalid_saved_data(self):
        cases = [[], {'id':'a'}, record(me='100'), record(total=True), record(date='20261001'), record(date='wrong'), record(bank=None), record(memo='bad\x00text'), record(id='')]
        for value in cases:
            with self.subTest(value=value):
                s = fake_store()
                s.sheet.rows.append(['e','time','save',json.dumps(value)])
                with self.assertRaises(LedgerDataError): s.load()

    def test_invalid_saved_plan(self):
        for plan in ({}, {'mother':-1,'me':1}, {'mother':True,'me':1}, {'mother':1,'me':'2'}, {'mother':MAX_AMOUNT+1,'me':0}):
            s=fake_store()
            s.sheet.rows.append(['e','time','plan',json.dumps(plan)])
            with self.assertRaises(LedgerDataError): s.load()

    def test_corrupt_json_and_events(self):
        for row in (['e','time','save','broken'], ['e','time','unknown','{}'], ['e','time'], ['', 'time','plan',json.dumps(DEFAULT_PLAN)]):
            s=fake_store(); s.sheet.rows.append(row)
            with self.assertRaises(LedgerDataError): s.load()

    def test_overpayment_from_saved_events(self):
        s=fake_store()
        for i in range(2):
            value=record(id=str(i),mother=60_000_000,me=0,total=60_000_000)
            s.sheet.rows.append([str(i),'time','save',json.dumps(value)])
        with self.assertRaises(LedgerDataError): s.load()

    def test_edit_cannot_exceed_remaining(self):
        s=fake_store()
        s.mutate('save',record(id='a',mother=60_000_000,me=0,total=60_000_000),s.load()[2],TODAY)
        s.mutate('save',record(id='b',mother=30_000_000,me=0,total=30_000_000),s.load()[2],TODAY)
        with self.assertRaises(ValueError):
            s.mutate('save',record(id='a',mother=80_000_000,me=0,total=80_000_000),s.load()[2],TODAY)
        self.assertEqual(balances(s.load()[0])['mother'],10_000_000)

    def test_response_loss_after_success(self):
        s=fake_store(); original=s.sheet.append_row
        def lost(row, **kwargs):
            original(row,**kwargs)
            raise TimeoutError('response lost')
        s.sheet.append_row=lost
        s.mutate('save',record(),s.load()[2],TODAY)
        self.assertEqual(len(s.sheet.rows),2)
        self.assertEqual(len(s.load()[0]),1)

    def test_failure_before_save(self):
        s=fake_store()
        s.sheet.append_row=MagicMock(side_effect=TimeoutError())
        with self.assertRaises(TimeoutError): s.mutate('save',record(),s.load()[2],TODAY)
        self.assertEqual(s.load()[0],[])

    def test_concurrent_saves(self):
        s=fake_store(); revision=s.load()[2]; results=[]
        def save(i):
            try: s.mutate('save',record(id=str(i)),revision,TODAY); results.append('saved')
            except ValueError: results.append('conflict')
        workers=[threading.Thread(target=save,args=(i,)) for i in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join()
        self.assertCountEqual(results,['saved','conflict'])
        self.assertEqual(len(s.load()[0]),1)

    def test_duplicate_event_replay(self):
        value=['e','time','save',json.dumps(record())]
        rows,plan=fold([value,value])
        self.assertEqual(len(rows),1)

    def test_connection_initialization(self):
        import gspread
        for existing in ([], [HEADER + ['', '']], [['wrong']]):
            client=MagicMock(); sheet=client.open_by_key.return_value.worksheet.return_value
            sheet.get_all_values.return_value=existing
            with patch('storage.service_account_info',return_value={}), patch('storage.Credentials.from_service_account_info'), patch('storage.gspread.authorize',return_value=client):
                config={'gcp_service_account':{}, 'spreadsheet_id':' https://docs.google.com/spreadsheets/d/test-id/edit '}
                if existing == [['wrong']]:
                    with self.assertRaises(SheetFormatError): GoogleStore(config)
                    sheet.append_row.assert_not_called()
                else:
                    GoogleStore(config)
                    client.open_by_key.assert_called_once_with('test-id')
                    client.set_timeout.assert_called_once_with((10,30))
                    if not existing: sheet.append_row.assert_called_once_with(HEADER,value_input_option='RAW')
        client=MagicMock(); book=client.open_by_key.return_value
        book.worksheet.side_effect=gspread.WorksheetNotFound()
        book.add_worksheet.return_value.get_all_values.return_value=[]
        with patch('storage.service_account_info',return_value={}), patch('storage.Credentials.from_service_account_info'), patch('storage.gspread.authorize',return_value=client):
            GoogleStore({'gcp_service_account':{},'spreadsheet_id':'id'})
        book.add_worksheet.assert_called_once_with('ledger_events_v1',rows=2000,cols=4)

    def test_safe_connection_error_screen(self):
        import streamlit as st
        for error in (KeyFormatError('PRIVATE-SECRET'), LedgerDataError('PRIVATE-SECRET'), SheetFormatError('PRIVATE-SECRET'), TimeoutError('PRIVATE-SECRET')):
            st.cache_resource.clear()
            with patch('storage.GoogleStore',side_effect=error):
                app=AppTest.from_file('app.py')
                app.secrets['login']={'salt':'test','password_hash':'test'}
                app.session_state['authenticated_until']=time.time()+1000
                app.run()
                self.assertFalse(app.exception)
                self.assertTrue(app.error)
                self.assertNotIn('PRIVATE-SECRET',str(app))

    def test_payoff_against_monthly_simulation(self):
        import random
        rng=random.Random(19)
        for _ in range(1000):
            remaining=rng.randrange(1,100_000_001); monthly=rng.randrange(1_000_000,10_000_001); paid=rng.randrange(0,20_000_001)
            left=remaining-max(monthly-paid,0); count=0
            while left>0: left-=monthly; count+=1
            self.assertEqual(payoff(remaining,monthly,paid,TODAY),month_add(TODAY,count))

    def test_fully_paid_and_interest_only(self):
        rows=[record(mother=100_000_000,me=100_000_000,total=200_000_000)]
        validate(rows[0],[],TODAY)
        validate(record(id='interest',mother=0,me=0,interest=100_000,total=100_000),rows,TODAY)
        self.assertEqual(balances(rows),{'mother':0,'me':0})
        self.assertEqual(payoff(0,0,0,TODAY),TODAY)

    def test_key_and_sheet_normalization(self):
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
        for value in (pem, pem.replace('\n', '\\n'), '\n' + pem + '  '):
            self.assertEqual(service_account_info({'private_key': value})['private_key'], pem)
        with self.assertRaises(KeyFormatError):
            service_account_info({'private_key': '-----BEGIN PRIVATE KEY-----\nbroken\n-----END PRIVATE KEY-----'})
        rows = [[cell + ' ' for cell in HEADER] + ['', ''], ['id','time','save','{}','','']]
        self.assertEqual(clean_rows(rows), [HEADER, ['id','time','save','{}']])
        self.assertEqual(clean_rows([HEADER + ['keep']])[0][-1], 'keep')
    def test_validation(self):
        r=record(); validate(r,[],TODAY)
        self.assertEqual(balances([r]),{'mother':96_000_000,'me':99_000_000})
        for invalid in [record(total=1),record(me=101_000_000,total=105_000_000),record(date='2026-10-02'),record(interest=-1)]:
            with self.assertRaises(ValueError): validate(invalid,[],TODAY)
        validate(record(total=5_100_000,interest=100_000),[],TODAY)
    def test_payoff(self):
        self.assertEqual(payoff(100_000_000,4_000_000,0,TODAY),date(2028,10,1))
        self.assertEqual(payoff(100_000_000,1_000_000,0,TODAY),date(2035,1,1))
        self.assertEqual(payoff(96_000_000,4_000_000,4_000_000,TODAY),date(2028,10,1))
        self.assertIsNone(payoff(1,0,0,TODAY))
        self.assertEqual(payoff(0,0,0,TODAY),TODAY)
        self.assertEqual(payoff(500_000,1_000_000,0,TODAY),TODAY)
        self.assertEqual(payoff(500_000,1_000_000,1_000_000,TODAY),date(2026,11,1))
        self.assertEqual(payoff(80_000_000,1_000_000,20_000_000,TODAY),date(2033,6,1))
    def test_excel(self):
        rows=[record(memo='=HYPERLINK("evil")')]
        wb=load_workbook(BytesIO(excel(rows,DEFAULT_PLAN,TODAY)))
        self.assertEqual(wb['상환 내역']['I2'].data_type,'s')
        self.assertEqual(wb['잔액 요약']['D2'].value,96_000_000)
    def test_events_and_conflict(self):
        s=fake_store(); rev=s.load()[2]
        s.mutate('save',record(),rev,TODAY)
        with self.assertRaises(ValueError): s.mutate('plan',DEFAULT_PLAN,rev,TODAY)
        s.mutate('save',record(total=6_000_000,me=2_000_000),s.load()[2],TODAY)
        self.assertEqual(len(s.load()[0]),1)
        s.mutate('delete',{'id':'a'},s.load()[2],TODAY)
        self.assertEqual(s.load()[0],[])
    def test_login_blocks(self):
        app=AppTest.from_file('app.py').run()
        self.assertFalse(app.exception)
        self.assertTrue(app.error)
        self.assertEqual(len(app.dataframe),0)
    def test_dashboard(self):
        s=fake_store()
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(app.get('plotly_chart')),3)
            self.assertEqual(len(app.tabs),3)
            for b in app.button:
                if b.label=='확인한 금액 저장': b.click(); break
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(app.error)
            self.assertEqual(s.load()[0],[])
            for widget in app.text_input:
                if widget.label=='송금 은행': widget.set_value('국민은행')
                if widget.label=='실제 송금자명': widget.set_value('본인')
            for widget in app.number_input:
                if widget.label=='엄마 원금 상환액': widget.set_value(4_000_000)
                if widget.label=='본인 원금 상환액': widget.set_value(1_000_000)
                if widget.label=='실제 총 송금액': widget.set_value(5_000_000)
            for button in app.button:
                if button.label=='확인한 금액 저장': button.click(); break
            app.run()
            self.assertFalse(app.exception)
            self.assertEqual(len(s.load()[0]),1)
            self.assertEqual(len(app.dataframe),1)
            self.assertTrue(app.success)
if __name__=='__main__': unittest.main()
