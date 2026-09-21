import sys
from pathlib import Path
import pytest
from fastapi import HTTPException
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tiktok_ads_dashboard import summarize, METRICS
from tiktok_patrol import today_for

def fixture():
    values={'成本':[10,30], 'SKU 订单数':[5,10], '平均下单成本':[2,3], '总收入':[100,150], 'ROI':[10,5]}
    return {'days':['2026-09-13','2026-09-14'],'series':[{'kind':'ads','label':name,'currency':'USD' if name in ('成本','平均下单成本','总收入') else '', 'timezone':'Asia/Shanghai','points':[{'day':day,'value':value} for day,value in zip(['2026-09-13','2026-09-14'],values[name])]} for name in METRICS]}

def test_weighted_period_metrics():
    result=summarize(fixture())
    assert result['complete'] and result['recorded_days']==2
    assert result['values']['ROI']==6.25
    assert result['values']['平均下单成本']==pytest.approx(40/15)
    assert result['values']['成本']==40

def test_missing_days_remain_partial_and_single_day_preserves_platform():
    data=fixture();data['days'].append('2026-09-15')
    result=summarize(data);assert not result['complete'] and result['recorded_days']==2
    for s in data['series']:s['points']=s['points'][:1]
    result=summarize(data);assert result['values']['ROI']==10 and result['recorded_days']==1

def test_zero_denominator_and_currency_guard():
    data=fixture()
    for s in data['series']:
        if s['label'] in ('成本','SKU 订单数'):
            for p in s['points']:p['value']=0
    result=summarize(data);assert result['values']['ROI'] is None and result['values']['平均下单成本'] is None
    data['series'][0]['currency']='MYR'
    with pytest.raises(HTTPException):summarize(data)

def test_account_timezone_supported():
    assert today_for({'timezone':'Asia/Shanghai'})==today_for({'timezone':'Asia/Kuala_Lumpur'})
