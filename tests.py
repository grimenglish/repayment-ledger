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
from hana import HANA_PRINCIPAL, HANA_SHARES, monthly_interest, repayment_fee, hana_balance, hana_balances, hana_unallocated, hana_excel
from backup import backup_state, backup_excel, next_year
TODAY=date(2026,10,1)
def record(**kw):
    r=dict(id='a',date='2026-10-01',bank='국민',sender='본인',total=5_000_000,mother=4_000_000,me=1_000_000,interest=0,memo='')
    r.update(kw)
    return r
def bank_record(**kw):
    r=dict(id='hana-a',date='2026-10-01',principal=10_000_000,interest=0,fee=49_000,fee_basis='estimate',memo='')
    r.update(kw)
    r.setdefault('mother',0)
    r.setdefault('me',r['principal']-r['mother'])
    r.setdefault('mother_interest',0)
    r.setdefault('me_interest',r['interest']-r['mother_interest'])
    return r
class Sheet:
    def __init__(self): self.rows=[HEADER.copy()]
    def get_all_values(self): return [r.copy() for r in self.rows]
    def append_row(self,row,**kw): self.rows.append(row)
    def col_values(self,col): return [r[col-1] for r in self.rows]
def fake_store():
    s=GoogleStore.__new__(GoogleStore); s.sheet=Sheet(); s.lock=threading.RLock(); return s
class Tests(unittest.TestCase):
    def setUp(self):
        import streamlit as st
        st.cache_resource.clear()

    def test_annual_backup_dates(self):
        value=['e','2026-10-01T01:00:00+00:00','save',json.dumps(record())]
        self.assertFalse(backup_state([value],date(2027,9,30))['overdue'])
        self.assertTrue(backup_state([value],date(2027,10,1))['overdue'])
        done=['b','2027-10-01T01:00:00+00:00','backup_confirm',json.dumps({'date':'2027-10-01','revision':'a'*64})]
        status=backup_state([value,done],date(2027,10,1))
        self.assertFalse(status['overdue'])
        self.assertEqual(status['due'],date(2028,10,1))
        self.assertEqual(next_year(date(2028,2,29)),date(2029,2,28))
        self.assertIsNone(backup_state([],TODAY)['due'])

    def test_full_backup_includes_replayable_events(self):
        from hana import fold_hana
        s=fake_store()
        s.mutate('save',record(memo='=1+1'),s.load()[2],TODAY)
        s.mutate('hana_save',bank_record(),s.load()[2],TODAY)
        records,plan,bank,revision,state=s.load_details(include_backup=True)
        wb=load_workbook(BytesIO(backup_excel(records,plan,bank,state['events'],TODAY,revision)))
        self.assertEqual(len(wb.sheetnames),8)
        self.assertEqual(wb['상환 내역']['I2'].data_type,'s')
        self.assertEqual(wb['하나은행 상환 내역']['C2'].value,10_000_000)
        events=[list(row) for row in wb['원본 이벤트 이력'].iter_rows(min_row=2,values_only=True)]
        self.assertEqual(fold(events),(records,plan))
        self.assertEqual(fold_hana(events),bank)

    def test_backup_confirmation_keeps_records(self):
        s=fake_store()
        s.mutate('save',record(),s.load()[2],TODAY)
        old=s.load_details(); revision=old[3]
        with self.assertRaises(ValueError): s.mutate('backup_confirm',{'date':TODAY.isoformat(),'revision':'a'*64},revision,TODAY)
        s.mutate('backup_confirm',{'date':TODAY.isoformat(),'revision':revision},revision,TODAY)
        current=s.load_details(include_backup=True)
        self.assertEqual(current[:3],old[:3])
        self.assertEqual(current[4]['last'],TODAY)
        self.assertEqual(current[4]['due'],date(2027,10,1))

    def test_backup_ui_confirm_requires_current_snapshot(self):
        import streamlit as st
        st.cache_resource.clear(); s=fake_store()
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            self.assertNotIn('confirm_full_backup',[button.key for button in app.button])
            app.session_state['backup_downloaded']={'revision':'a'*64,'date':TODAY.isoformat()}
            app.run()
            self.assertNotIn('confirm_full_backup',[button.key for button in app.button])
            app.session_state['backup_downloaded']={'revision':s.load()[2],'date':TODAY.isoformat()}
            app.run()
            app.button(key='confirm_full_backup').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(s.load_details(include_backup=True)[4]['last'],TODAY)
            self.assertEqual(s.load_details()[0],[])

    def test_undo_new_and_edited_records(self):
        for kind,first,edited in [('save',record(),record(me=2_000_000,total=6_000_000)),('hana_save',bank_record(),bank_record(principal=5_000_000,fee=24_500))]:
            s=fake_store()
            s.mutate(kind,first,s.load()[2],TODAY)
            s.undo_save(kind,first,None,s.load()[2],TODAY)
            self.assertEqual(s.load_details()[0 if kind=='save' else 2],[])
            s.mutate(kind,first,s.load()[2],TODAY)
            s.mutate(kind,edited,s.load()[2],TODAY)
            s.undo_save(kind,edited,first,s.load()[2],TODAY)
            self.assertEqual(s.load_details()[0 if kind=='save' else 2],[first])

    def test_undo_blocks_later_changes(self):
        s=fake_store(); first=record(); second=record(me=2_000_000,total=6_000_000)
        s.mutate('save',first,s.load()[2],TODAY)
        revision=s.load()[2]
        s.mutate('save',second,revision,TODAY)
        with self.assertRaises(ValueError): s.undo_save('save',first,None,revision,TODAY)
        with self.assertRaises(ValueError): s.undo_save('save',first,None,s.load()[2],TODAY)
        self.assertEqual(s.load()[0],[second])

    def test_undo_restores_legacy_bank_record(self):
        s=fake_store(); legacy=bank_record()
        for key in ('mother','me','mother_interest','me_interest'): legacy.pop(key)
        s.sheet.rows.append(['old','time','hana_save',json.dumps(legacy)])
        allocated=bank_record(mother=2_000_000)
        s.mutate('hana_save',allocated,s.load()[2],TODAY)
        s.undo_save('hana_save',allocated,legacy,s.load()[2],TODAY)
        self.assertEqual(s.load_details()[2],[legacy])

    def test_easy_family_repeat_person_buttons_and_undo(self):
        import streamlit as st
        st.cache_resource.clear(); s=fake_store()
        previous=record(mother=0,me=1_000_000,total=1_000_000,date='2026-09-30')
        s.mutate('save',previous,s.load()[2],TODAY)
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            self.assertTrue(any(m.label=='내 남은 대출' and m.value=='149,000,000원' for m in app.metric))
            app.button(key='new_manual_repeat').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio(key='new_manual_person').value,'본인만')
            self.assertNotIn('new_manual_mother',[widget.key for widget in app.number_input])
            self.assertEqual(app.number_input(key='new_manual_me').value,1_000_000)
            self.assertEqual(app.date_input(key='new_manual_date').value,TODAY)
            app.button(key='new_manual_me_plus100k').click().run()
            self.assertEqual(app.number_input(key='new_manual_me').value,1_100_000)
            app.button(key='new_manual_me_plus1m').click().run()
            self.assertEqual(app.number_input(key='new_manual_me').value,2_100_000)
            app.button(key='new_manual_me_reset').click().run()
            self.assertEqual(app.number_input(key='new_manual_me').value,0)
            app.button(key='new_manual_repeat').click().run()
            app.button(key='new_manual_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(s.load()[0]),2)
            app.button(key='undo_last_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(s.load()[0],[previous])
            self.assertNotIn('undo_last_save',[button.key for button in app.button])

    def test_easy_hana_repeat_and_undo(self):
        import streamlit as st
        st.cache_resource.clear(); s=fake_store()
        previous=bank_record(date='2026-09-30',mother=10_000_000,me=0)
        s.mutate('hana_save',previous,s.load()[2],TODAY)
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            app.button(key='hana_new_repeat').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.radio(key='hana_new_person').value,'엄마만')
            self.assertNotIn('hana_new_me',[widget.key for widget in app.number_input])
            self.assertEqual(app.number_input(key='hana_new_mother').value,10_000_000)
            app.button(key='hana_new_mother_plus1m').click().run()
            self.assertEqual(app.number_input(key='hana_new_mother').value,10_000_000)
            app.button(key='hana_new_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(hana_balances(s.load_details()[2])['mother'],0)
            app.button(key='undo_last_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(s.load_details()[2],[previous])

    def test_repeat_limits_remaining_principal(self):
        import streamlit as st
        st.cache_resource.clear(); s=fake_store()
        s.mutate('hana_save',bank_record(mother=15_000_000,me=0,principal=15_000_000,fee=73_500),s.load()[2],TODAY)
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            app.button(key='hana_new_repeat').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.number_input(key='hana_new_mother').value,5_000_000)
            self.assertTrue(any('남은 원금에 맞춰' in info.value for info in app.info))

    def test_hana_mother_and_me_separate(self):
        s=fake_store()
        self.assertEqual(hana_balances([]),HANA_SHARES)
        self.assertEqual(monthly_interest(20_000_000),76_667)
        self.assertEqual(monthly_interest(50_000_000),191_667)
        s.mutate('hana_save',bank_record(principal=5_000_000,mother=5_000_000,fee=24_500),s.load()[2],TODAY)
        self.assertEqual(hana_balances(s.load_details()[2]),{'mother':15_000_000,'me':50_000_000})
        s.mutate('hana_save',bank_record(id='b',principal=10_000_000,mother=0,fee=49_000),s.load()[2],TODAY)
        self.assertEqual(hana_balances(s.load_details()[2]),{'mother':15_000_000,'me':40_000_000})
        self.assertEqual(monthly_interest(hana_balances(s.load_details()[2])['mother']),57_500)
        self.assertEqual(monthly_interest(hana_balances(s.load_details()[2])['me']),153_333)

    def test_hana_split_validation(self):
        s=fake_store()
        for value in (bank_record(mother=11_000_000,me=0),bank_record(principal=21_000_000,mother=21_000_000,fee=102_900),bank_record(principal=51_000_000,fee=249_900),bank_record(mother_interest=1,me_interest=0),bank_record(mother=True)):
            with self.assertRaises(ValueError): s.mutate('hana_save',value,s.load()[2],TODAY)

    def test_hana_legacy_preserved_and_allocated(self):
        s=fake_store(); legacy=bank_record()
        for key in ('mother','me','mother_interest','me_interest'): legacy.pop(key)
        s.sheet.rows.append(['old','time','hana_save',json.dumps(legacy)])
        bank=s.load_details()[2]
        self.assertEqual(hana_balance(bank),60_000_000)
        self.assertEqual(len(hana_unallocated(bank)),1)
        with self.assertRaises(ValueError): s.mutate('hana_save',bank_record(id='new'),s.load()[2],TODAY)
        s.mutate('hana_save',bank_record(mother=2_000_000),s.load()[2],TODAY)
        self.assertEqual(hana_unallocated(s.load_details()[2]),[])
        self.assertEqual(hana_balances(s.load_details()[2]),{'mother':18_000_000,'me':42_000_000})

    def test_hana_legacy_ui_allocation(self):
        import streamlit as st
        st.cache_resource.clear(); s=fake_store(); legacy=bank_record(interest=200_000)
        for key in ('mother','me','mother_interest','me_interest'): legacy.pop(key)
        s.sheet.rows.append(['old','time','hana_save',json.dumps(legacy)])
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            self.assertFalse(app.exception)
            app.number_input(key='hana_edit_hana-a_mother').set_value(2_000_000)
            app.number_input(key='hana_edit_hana-a_me').set_value(8_000_000)
            app.number_input(key='hana_edit_hana-a_mother_interest').set_value(50_000)
            app.number_input(key='hana_edit_hana-a_me_interest').set_value(150_000)
            app.button(key='hana_edit_hana-a_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(len(s.load_details()[2]),1)
            self.assertEqual(hana_unallocated(s.load_details()[2]),[])
            self.assertEqual(hana_balances(s.load_details()[2]),{'mother':18_000_000,'me':42_000_000})

    def test_hana_cost_calculation(self):
        self.assertEqual(monthly_interest(70_000_000),268_333)
        self.assertEqual(monthly_interest(60_000_000),230_000)
        self.assertEqual(monthly_interest(10_000_000),38_333)
        self.assertEqual(repayment_fee(10_000_000),49_000)
        self.assertEqual(repayment_fee(20_000_000),98_000)
        self.assertEqual(repayment_fee(70_000_000),343_000)
        self.assertEqual(monthly_interest(0),0)

    def test_hana_save_edit_delete_isolation(self):
        s=fake_store(); s.mutate('save',record(),s.load()[2],TODAY)
        family,plan,_,_=s.load_details()
        s.mutate('hana_save',bank_record(),s.load()[2],TODAY)
        current_family,current_plan,bank,revision=s.load_details()
        self.assertEqual((family,plan),(current_family,current_plan))
        self.assertEqual(hana_balance(bank),60_000_000)
        s.mutate('hana_save',bank_record(principal=20_000_000,fee=98_000),revision,TODAY)
        self.assertEqual(hana_balance(s.load_details()[2]),50_000_000)
        s.mutate('hana_delete',{'id':'hana-a'},s.load()[2],TODAY)
        self.assertEqual(s.load_details()[2],[])
        self.assertEqual(s.load()[0],family)

    def test_hana_invalid_and_overpayment(self):
        s=fake_store()
        for invalid in (bank_record(principal=80_000_000,fee=392_000),bank_record(fee=-1),bank_record(fee=1),bank_record(principal=True),bank_record(date='2026-10-02'),bank_record(memo='bad\x00')):
            with self.assertRaises(ValueError): s.mutate('hana_save',invalid,s.load()[2],TODAY)
        s.mutate('hana_save',bank_record(principal=60_000_000,mother=20_000_000,fee=294_000),s.load()[2],TODAY)
        with self.assertRaises(ValueError): s.mutate('hana_save',bank_record(id='b',principal=20_000_000,fee=98_000),s.load()[2],TODAY)
        self.assertEqual(hana_balance(s.load_details()[2]),10_000_000)

    def test_hana_actual_costs_and_excel(self):
        s=fake_store()
        s.mutate('hana_save',bank_record(interest=200_000,fee=12_345,fee_basis='actual',memo='=1+1'),s.load()[2],TODAY)
        records=s.load_details()[2]
        self.assertEqual(hana_balance(records),60_000_000)
        wb=load_workbook(BytesIO(hana_excel(records)))
        self.assertEqual(wb['하나은행 상환 내역']['E2'].value,12_345)
        self.assertEqual(wb['하나은행 상환 내역']['G2'].data_type,'s')
        self.assertEqual(wb['하나은행 요약']['B4'].value,60_000_000)

    def test_hana_ui_save_and_simulation(self):
        import streamlit as st
        st.cache_resource.clear(); s=fake_store()
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            app.number_input(key='hana_simulation_me').set_value(20_000_000).run()
            self.assertEqual(s.load_details()[2],[])
            app.number_input(key='hana_new_me').set_value(10_000_000).run()
            self.assertTrue(any(m.value=='49,000원' for m in app.metric))
            app.button(key='hana_new_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(hana_balance(s.load_details()[2]),60_000_000)
            self.assertEqual(s.load()[0],[])
            self.assertTrue(any(m.value=='약 230,000원' for m in app.metric))
            record_id=s.load_details()[2][0]['id']
            app.number_input(key='hana_edit_'+record_id+'_me').set_value(5_000_000).run()
            app.button(key='hana_edit_'+record_id+'_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(hana_balance(s.load_details()[2]),65_000_000)
            app.checkbox(key='hana_confirm_'+record_id).set_value(True).run()
            app.button(key='hana_delete_'+record_id).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(s.load_details()[2],[])

    def test_hana_full_repayment_ui(self):
        import streamlit as st
        st.cache_resource.clear(); s=fake_store()
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            app.number_input(key='hana_new_mother').set_value(20_000_000)
            app.number_input(key='hana_new_me').set_value(50_000_000).run()
            app.button(key='hana_new_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(hana_balance(s.load_details()[2]),0)
            self.assertTrue(any(m.value=='약 0원' for m in app.metric))

    def test_korean_amounts(self):
        for amount, expected in [(0,'영 원'), (100_000,'십만 원'), (1_000_000,'백만 원'), (10_000_000,'천만 원'), (4_000_000,'사백만 원'), (100_000_000,'일억 원'), (123_456_789,'일억 이천삼백사십오만 육천칠백팔십구 원')]:
            self.assertEqual(amount_words(amount),expected)

    def test_live_amounts_and_transfer_comparison(self):
        import streamlit as st
        st.cache_resource.clear()
        s=fake_store()
        with patch('storage.GoogleStore',return_value=s):
            app=AppTest.from_file('app.py')
            app.secrets['login']={'salt':'test','password_hash':'test'}
            app.session_state['authenticated_until']=time.time()+1000
            app.run()
            for widget in app.text_input:
                if widget.label=='송금 은행': widget.set_value('신한은행')
                if widget.label=='실제 송금자명': widget.set_value('본인')
            for widget in app.number_input:
                if widget.label=='엄마 원금 상환액': widget.set_value(4_000_000)
                if widget.label=='본인 원금 상환액': widget.set_value(100_000)
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any(c.value=='100,000원 · 십만 원' for c in app.caption))
            self.assertTrue(any(m.value=='4,100,000원' for m in app.metric))
            app.toggle(key='new_manual_compare').set_value(True).run()
            app.number_input(key='new_manual_total').set_value(5_000_000).run()
            app.button(key='new_manual_save').click().run()
            self.assertTrue(app.error)
            self.assertEqual(s.load()[0],[])
            app.toggle(key='new_manual_compare').set_value(False).run()
            app.number_input(key='new_manual_me').set_value(1_000_000).run()
            self.assertTrue(any(c.value=='1,000,000원 · 백만 원' for c in app.caption))
            self.assertTrue(any(m.value=='5,000,000원' for m in app.metric))
            app.button(key='new_manual_save').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(s.load()[0][0]['total'],5_000_000)

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
            self.assertEqual(len(app.tabs),8)
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
            self.assertEqual(len(app.get('plotly_chart')),6)
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
            self.assertEqual(len(app.get('plotly_chart')),6)
            self.assertEqual(len(app.tabs),8)
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
