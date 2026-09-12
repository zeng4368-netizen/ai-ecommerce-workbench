"""Generate an auditable inventory, not a fabricated per-control pass report."""
from pathlib import Path
import hashlib
import json
import re
from datetime import date

root=Path(__file__).resolve().parents[1]
routes={'日销异常1.html':'inventory','售后数据.html':'after / finance / creators','广告数据.html':'marketing',
        'TikTok_GMVMax广告经营管理看板v45_简约版_离线.html':'ads'}
items=[]
for name,route in routes.items():
    path=root/'modules'/name;text=path.read_text(encoding='utf-8')
    headings=list(dict.fromkeys(re.sub('<[^>]*>','',s).strip() for s in re.findall(r'<h[1-4]\b[^>]*>(.*?)</h[1-4]>',text,re.S)))
    headings=[h for h in headings if h and '${' not in h]
    functions=list(dict.fromkeys(re.findall(r'\bfunction\s+([\w$]+)\s*\(',text)))
    items.append({'source':'modules/'+name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'route':route,
      'integration':'原计算与视图通过版本化适配器运行；上传统一进入数据中心',
      'verification':'已验证整页加载和统一版本；不等于每个筛选组合均已逐项验收',
      'features':headings,'functions':functions})
result={'generated_on':date.today().isoformat(),'modules':items,
 'calculation_contracts':[
  {'engine':'日销','source':'buildDashboardData','input':'ERP + daily + warn','output':'products/detailData/kpis','verification':'原浏览器运行结果与服务端执行原函数逐字段相等；内嵌冻结值229处差异另存'},
  {'engine':'利润','source':'SKILL_PIPE.stage1/2/3','input':'订单/结算/产品包','output':'原表头、4张利润工作表、原百分比口径','verification':'原函数直接执行；Excel精度按浮点容差核对'},
  {'engine':'GMV清洗','source':'skills/GMV-MAX广告数据清晰/scripts/gmv_max_cleaner.py','input':'人员映射+广告素材+用户指定L7D起点','output':'固定15列','verification':'原脚本端到端测试'},
  {'engine':'日销异常查询','source':'原店铺导出下降规则','input':'店铺筛选后的完整日销表','output':'分页明细与全量数量','verification':'EXPOSE.TK 145商品中71项下滑待核查；不声称原因'}],
 'known_limits':['广告板块四脚本及49列规范缺失，未实现推测流水线','TikTok/马帮官方API尚未授权，仅预留接口','历史售后没有逐单原表，仅保留原汇总','售后当前每批最多4个月；月份标签由实际输入适配','营销旧页存在原有占位功能，未虚构广告素材数据','全控件、全部筛选组合的逐项验收仍需补充真实业务输入']}
(root/'assets/skill-coverage.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'modules':len(items),'features':sum(len(i['features']) for i in items)},ensure_ascii=False))
