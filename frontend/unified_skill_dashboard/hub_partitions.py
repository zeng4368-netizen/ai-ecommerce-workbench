"""Explicit shop/period partitions. Only one comparable period enters original engines."""
from collections import defaultdict
from copy import deepcopy
import re
from fastapi import HTTPException

SUPPORTED={'daily','gmv','bill'}
SHOP_COLUMNS={'daily':['店铺'],'gmv':['店铺','店编','店名','店铺名称'],'bill':['店编']}


def shop_key(value):
    return str(value or '').strip().casefold()


def split_entry(kind,entry,allow_unknown=False):
    columns=[entry['header'].index(h) for h in SHOP_COLUMNS[kind] if h in entry['header']]
    groups=defaultdict(list)
    for row in entry['rows']:
        shop=next((str(row[i]).strip() for i in columns if row[i] not in ('',None)),'')
        if not shop and allow_unknown:shop='历史店铺未标注'
        if not shop: raise HTTPException(422,'分区更新必须有原始店铺列且每行店铺非空；不把文件名猜测写入原字段。请核对原表或使用整体替换。')
        groups[shop].append(row)
    return [{**deepcopy(entry),'shop':shop,'rows':rows,'row_count':len(rows),
             'unassigned':allow_unknown and shop=='历史店铺未标注'} for shop,rows in groups.items()]


def key(entry):
    return bool(entry.get('unassigned')),shop_key(entry['shop']),entry['period'],entry.get('currency','')


def bootstrap(current,kind):
    from data_hub import table_of
    data=current['data'];meta=current['meta']['datasets'].get(kind,{})
    if kind=='daily':table=table_of(data['daily']['raw']['daily'])
    elif kind=='gmv':table=table_of(data['gmv']['rows'])
    else:table=data['bill']
    if not table['rows']:return []
    entry={**table,'name':'原已保存数据','sheet':'历史批次','period':meta.get('period',''),
           'currency':meta.get('currency',''),'shop':'','origin_version':current['version']}
    return split_entry(kind,entry,allow_unknown=True)


def prepare(current,groups):
    """Return active comparable tables plus an immutable-in-version partition ledger."""
    if any(kind not in SUPPORTED for kind in groups):
        raise HTTPException(422,'按店铺分区目前支持日销、广告明细、已处理账单；ERP等共享表请单独选择整体替换。')
    ledger=deepcopy(current['data'].get('partition_store',{}));active={};changes=[]
    for kind,entries in groups.items():
        existing=ledger.get(kind)
        if existing is None:existing=bootstrap(current,kind)
        target=(entries[0]['period'],entries[0].get('currency',''))
        if any(e.get('unassigned') and (e['period'],e.get('currency',''))==target for e in existing):
            raise HTTPException(422,'该周期历史数据有未标注店铺的行，无法确认与新店铺数据是否重叠。请核查完整原表后整体替换；其他周期可独立分区导入。')
        incoming=[]
        for entry in entries:incoming.extend(split_entry(kind,entry))
        indexed={key(e):e for e in existing};updates=defaultdict(list)
        for entry in incoming:updates[key(entry)].append(entry)
        for identity,parts in updates.items():
            first=parts[0]
            if any(e['header']!=first['header'] for e in parts):raise HTTPException(422,'同店铺同周期的字段顺序不一致，不能静默合并。')
            combined={**first,'rows':[r for e in parts for r in e['rows']]}
            old=indexed.get(identity)
            unchanged=bool(old and old['header']==combined['header'] and old['rows']==combined['rows'])
            changes.append({'kind':kind,'shop':first['shop'],'period':first['period'],'currency':first.get('currency',''),
                            'operation':'unchanged' if unchanged else 'revision' if old else 'new',
                            'before_rows':len(old['rows']) if old else 0,'after_rows':len(combined['rows'])})
            indexed[identity]=combined
        ledger[kind]=list(indexed.values())
        selected=[e for e in ledger[kind] if (e['period'],e.get('currency',''))==target]
        # The original engine receives exact original columns, never a cross-period union.
        if any(e['header']!=selected[0]['header'] for e in selected):
            raise HTTPException(422,'同周期历史分区与新表字段顺序不同；请核对规范，不能悄悄丢列。')
        active[kind]=selected
    return active,ledger,changes


def index(current):
    result=[]
    for kind,entries in current['data'].get('partition_store',{}).items():
        grouped=defaultdict(list)
        for entry in entries:grouped[(entry['period'],entry.get('currency',''))].append(entry)
        meta=current['meta']['datasets'].get(kind,{})
        for (period,currency),parts in grouped.items():
            result.append({'kind':kind,'period':period,'currency':currency,'shops':[e['shop'] for e in parts],
                           'rows':sum(len(e['rows']) for e in parts),'active':meta.get('period')==period and meta.get('currency','')==currency})
    return result
