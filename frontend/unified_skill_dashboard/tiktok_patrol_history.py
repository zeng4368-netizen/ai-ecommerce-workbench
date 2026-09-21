"""Daily views over immutable capture records; never invent missing history."""
import csv
import io
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from fastapi.responses import Response
from ziniao_bridge import load_stores


def daily_history(live, store_id, start, end):
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise HTTPException(422, '请选择有效的开始和结束日期') from None
    if first > last or (last-first).days > 365:
        raise HTTPException(422, '开始日期不能晚于结束日期，最多查看 366 天')
    stores = load_stores(live.patrol.selectors)
    if store_id != 'all':
        live.patrol.store(store_id)
        stores = {store_id: stores[store_id]}
    days = [(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]
    with live.db() as con:
        live.schema(con)
        records = [json.loads(r[0]) for r in con.execute('SELECT value FROM tiktok_patrol_live_runs ORDER BY rowid')]
    # Select the latest successful SECTION for each local day. A later failed run
    # must not erase a previous successful read; repeated reads never sum values.
    latest = {}
    versions = {}
    for r in records:
        if r['store_id'] not in stores:
            continue
        for kind, section in r.get('sections', {}).items():
            day = (datetime.fromisoformat(section['captured_at']).astimezone(ZoneInfo(r['timezone'])).date().isoformat()
                   if kind == 'homepage' else section['period'])
            if not start <= day <= end:
                continue
            key = (r['store_id'], kind, day)
            versions[key] = versions.get(key, 0)+1
            if key not in latest or section['captured_at'] >= latest[key][1]['captured_at']:
                latest[key] = (r, section)
    series = {}
    rows = []
    for (sid, kind, day), (r, section) in sorted(latest.items()):
        values = section['data']['cards'] if kind == 'homepage' else section['data']
        for metric in values:
            currency = metric.get('currency', '')
            key = (sid, kind, metric['label'], currency)
            s = series.setdefault(key, {'store_id': sid, 'shop': stores[sid]['shop'], 'kind': kind,
                'label': metric['label'], 'currency': currency, 'timezone': section.get('timezone',r['timezone']), 'points': {}})
            point = {'day': day, 'value': metric['value'], 'run_id': r['id'], 'captured_at': section['captured_at'],
                     'versions': versions[(sid, kind, day)], 'sha256': section['sha256'],
                     'platform_change_pct': metric.get('change_pct')}
            s['points'][day] = point
    for s in series.values():
        points = s['points']
        for day in days:
            if day not in points:
                continue
            point = points[day]
            prev = points.get((date.fromisoformat(day)-timedelta(days=1)).isoformat())
            point['delta'] = point['value']-prev['value'] if prev else None
            point['daily_change_pct'] = ((point['value']/prev['value']-1)*100
                                         if prev and prev['value'] != 0 else None)
            rows.append({**{k:v for k,v in s.items() if k != 'points'}, **point})
        s['points'] = [points.get(day, {'day':day,'value':None}) for day in days]
    return {'days': days, 'series': list(series.values()), 'rows': rows,
            'stores': [{'store_id':sid,'shop':v['shop'],'currency':v['currency']} for sid,v in stores.items()],
            'recorded_days': len({r['day'] for r in rows}), 'range_days':len(days)}


def history_csv(data):
    out = io.StringIO()
    writer = csv.writer(out)
    keys = ['day','shop','kind','label','value','currency','timezone','delta','daily_change_pct','captured_at','versions','run_id','sha256']
    writer.writerow(['日期','店铺','模块','指标','数值','币种','时区','较前日变化','日环比%','采集时间','当日版本数','记录ID','SHA256'])
    for row in data['rows']:
        values = [row.get(k, '') if row.get(k) is not None else '' for k in keys]
        writer.writerow(["'"+v if isinstance(v,str) and v.startswith(('=','+','-','@','\t','\r')) else v for v in values])
    return Response('\ufeff'+out.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition':'attachment; filename="tiktok-daily-history.csv"'})
