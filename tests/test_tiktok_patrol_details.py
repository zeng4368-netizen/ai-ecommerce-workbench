import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'frontend/unified_skill_dashboard'))
import pytest
from tiktok_patrol_details import review_day,split_orders,parse_violation

def test_review_days_not_text_sentiment():
 assert review_day('14 de setembro de 2026\nOkay good')=='2026-09-14'
 assert review_day('September 14, 2026\nGood')=='2026-09-14'
 with pytest.raises(ValueError):review_day('missing date')

def test_order_ids_preserve_precision_and_multiple_products():
 text='订单 ID:\n586060741197530232\n商品 A\n商品 B\n订单 ID\n:\n585773508942333412\n退货退款'
 rows=split_orders(text)
 assert [r['order_id'] for r in rows]==['586060741197530232','585773508942333412']
 assert '商品 B' in rows[0]['text']

def test_violation_rejects_different_drawer():
 with pytest.raises(ValueError):parse_violation('违规详情ID: 9999','8888')

def test_wallet_unbound_never_navigates():
 from tiktok_patrol_details import DetailReader
 reader=object.__new__(DetailReader);reader.config={'wallet_accounts':{}};reader.sid='another-shop'
 reader.visit=lambda *args,**kwargs:pytest.fail('unbound account must never open EXPOSE payment URL')
 with pytest.raises(ValueError,match='尚未绑定'):reader.wallet()

def test_date_range_and_browser_lease(tmp_path):
 import sqlite3,time
 from contextlib import contextmanager
 from types import SimpleNamespace
 from tiktok_patrol_details import DetailPatrol,DetailRequest
 from fastapi import HTTPException
 from datetime import date
 @contextmanager
 def db():
  with sqlite3.connect(tmp_path/'test.db') as con:yield con
 patrol=SimpleNamespace(store=lambda sid:{'shop':'Test','timezone':'Asia/Kuala_Lumpur'})
 live=SimpleNamespace(patrol=patrol,db=db)
 service=DetailPatrol(live)
 service.config=lambda:{'version':'test'}
 with pytest.raises(HTTPException) as error:service.create(DetailRequest(store_id='a',start=date(2026,9,2),end=date(2026,9,1)),False)
 assert error.value.status_code==422
 with db() as con:
  service.schema(con);con.execute('INSERT INTO ziniao_browser_lease VALUES(1,?,?)',('other-task',time.time()+180))
 with pytest.raises(HTTPException) as error:service.create(DetailRequest(store_id='a'),False)
 assert error.value.status_code==409
 with db() as con:assert con.execute('SELECT owner FROM ziniao_browser_lease').fetchone()[0]=='other-task'
