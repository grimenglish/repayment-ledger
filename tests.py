import unittest
import json
import time
import threading
from datetime import date
from io import BytesIO
from unittest.mock import patch
from openpyxl import load_workbook
from streamlit.testing.v1 import AppTest
from core import *
from storage import GoogleStore, HEADER
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
