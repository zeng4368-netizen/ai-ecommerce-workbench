"""Conservative cross-table joins: confirmed keys, compatible periods, separate currencies."""
import json
from data_hub import engine,objects

def linked_product(hub,current,shop,product_id):
    with hub.db() as con: mappings=[json.loads(r[0]) for r in con.execute('SELECT value FROM hub_mappings')]
    matches=[m for m in mappings if m['shop']==shop and m['product_id']==product_id and m['confirmed']]
    if len(matches)!=1 or not matches[0]['sku']:return {'status':'missing_mapping','reason':'需要唯一且已人工确认的店铺、商品 ID、SKU 对应关系；不按相似名称猜测。'}
    m=matches[0];data=current['data'];meta=current['meta']['datasets']
    periods={k:meta.get(k,{}).get('period') for k in ('gmv','daily','erp')}
    if not periods['gmv'] or len(set(periods.values()))!=1:
        return {'status':'incomparable','mapping':m,'periods':periods,'reason':'广告、日销、ERP 观察窗口不一致，暂不输出跨表结论。'}
    ads=[r for r in data['gmv']['rows'] if str(r.get('商品 ID',''))==product_id and str(r.get('店铺',r.get('店编','')))==shop]
    daily=[r for r in data['daily']['raw']['daily'] if str(r.get('库存SKU',''))==m['sku'] and r.get('店铺')==shop]
    stock=[r for r in data['daily']['raw']['erp'] if str(r.get('库存SKU编号',''))==m['sku']]
    if not ads or not daily or not stock:return {'status':'incomplete','mapping':m,'reason':'映射已确认，但同批次缺少广告、日销或库存对应行，不把缺失当成零。'}
    metrics=engine({'op':'ad_metrics','rows':ads})
    return {'status':'matched','version':current['version'],'mapping':m,'periods':periods,'ads_by_currency':metrics,
            'daily_rows':daily,'inventory_rows':stock,
            'reason':'只展示已确认同周期对象的联合证据；ERP 为该 SKU 仓库库存，非店铺独占库存。不相加币种，不推断投放因果或可实现收益。'}
