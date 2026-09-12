"""Inspect schema and aggregate validation only; never print buyer columns/rows."""
import csv,json,sys
from pathlib import Path
from openpyxl import load_workbook
p=Path(sys.argv[1])
if p.suffix=='.csv':
    with p.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.reader(f))
    print(json.dumps({'headers':rows[0],'rows':len(rows)-1},ensure_ascii=False))
    h=rows[0]
    from collections import Counter
    for keys in [('Order ID','SKU ID'),('Order ID','SKU ID','Package ID')]:
        c=Counter(tuple(r[h.index(k)].strip() for k in keys) for r in rows[1:])
        print('key_check',keys,'duplicates',sum(v-1 for v in c.values()))
    for key in ['Order ID','SKU ID','Created Time','Order Status','Quantity']:
        if key in h:
            v=[r[h.index(key)] for r in rows[1:]]
            print(key,json.dumps({'unique':len(set(v)),'blank':v.count(''),'min':min(v),'max':max(v)},ensure_ascii=False))
else:
    b=load_workbook(p,read_only=True,data_only=False)
    for s in b:
        s.reset_dimensions()  # TikTok streaming exports can carry stale worksheet dimensions.
        rows=list(s.values)
        print(json.dumps({'sheet':s.title,'rows':len(rows),'first_rows':rows[:1]},ensure_ascii=False,default=str))
        if s.title=='订单详情':
            from collections import Counter
            from decimal import Decimal
            h=rows[0]; data=[r for r in rows[1:] if any(v is not None for v in r)]
            for names in [('订单ID/调整单ID','交易类型','相关订单 ID'),('订单ID/调整单ID','交易类型','订单结算时间')]:
                cc=Counter(tuple(r[h.index(k)] for k in names) for r in data)
                print('uniqueness',names,'duplicates',sum(v-1 for v in cc.values()),'blank IDs',sum(not r[0] for r in data))
            print('adjustment-safe-fields',[[r[h.index(k)] for k in ['订单ID/调整单ID','交易类型','相关订单 ID','订单结算时间','调整金额']] for r in data if r[1]!='订单'])
            print('checks',json.dumps({'rows':len(data),'widths':dict(Counter(len(r) for r in data)),
              'duplicate_keys':len(data)-len({tuple(str(r[h.index(k)]).strip() for k in ['订单ID/调整单ID','交易类型']) for r in data}),
              'types':dict(Counter(r[1] for r in data)), 'min_date':min(r[3] for r in data),'max_date':max(r[3] for r in data),
              'totals':{k:str(sum(Decimal(str(r[h.index(k)] or 0)) for r in data)) for k in ['结算总金额','总收入','总费用','享受商家折扣后的退款小计','调整金额']}},ensure_ascii=False))
        if s.title=='报告':print(json.dumps([[x for x in r if x is not None] for r in rows if any(x is not None for x in r)],ensure_ascii=False,default=str))
    b.close()
