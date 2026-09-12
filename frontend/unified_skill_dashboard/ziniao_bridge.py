"""Restricted CLI adapter. No direct Bridge HTTP, cookies or model-supplied commands."""
import hashlib
import copy
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from fastapi import HTTPException


DEFAULT_STORE = '27007200298613'


def load_stores(path):
    value = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    return value.get('ziniao_stores') or {DEFAULT_STORE:{'shop':'MS0237-EXPOSE.TK','currency':'MYR','timezone':'Asia/Kuala_Lumpur','profile':{}}}


def load_profile(path, store_id=None):
    value = yaml.safe_load(Path(path).read_text(encoding='utf-8')) or {}
    base=value.get('ziniao_collection', {})
    if store_id is None:return base
    binding=load_stores(path).get(store_id)
    if not binding:raise HTTPException(422,'店铺未绑定，不能导出')
    def merge(left,right):
        result=copy.deepcopy(left)
        for key,v in right.items():
            result[key]=merge(result.get(key,{}),v) if isinstance(v,dict) else copy.deepcopy(v)
        return result
    return merge(base,binding.get('profile',{}))


def profile_hash(profile):
    return hashlib.sha256(json.dumps(profile, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Bridge:
    def __init__(self, selectors):
        self.selectors = Path(selectors)

    def command(self):
        # Call the installed npm JS entrypoint through node, never cmd.exe or shell=True.
        cli = shutil.which('ziniao-cli')
        if not cli: raise HTTPException(503, '未找到已安装的 ziniao-cli')
        if os.name == 'nt':
            script = Path(cli).parent/'node_modules/@ziniao-open/cli/scripts/run.js'
            node = shutil.which('node')
            if not node or not script.is_file(): raise HTTPException(503, '未找到紫鸟 npm 入口；请检查全局安装')
            return [node, str(script)]
        return [cli]

    def run(self, args, raw=False):
        allowed = {('doctor',), ('store', 'resolve'), ('store', 'open'), ('page', 'visit'),
                   ('page', 'input'), ('page', 'click'), ('page', 'exec'), ('page', 'screenshot'), ('page','extract')}
        if tuple(args[:1 if args[0] == 'doctor' else 2]) not in allowed:
            raise HTTPException(422, '非白名单 CLI 命令')
        try:
            proc = subprocess.run(self.command()+args, capture_output=True, timeout=45, shell=False,
                                  creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                                  env={**os.environ, 'ZINIAO_CLI_NO_UPDATE_CHECK': '1'})
        except (OSError, subprocess.TimeoutExpired):
            raise HTTPException(503, '紫鸟命令无法完成；请检查客户端，任务可恢复') from None
        def decode(value):
            try: return value.decode('utf-8')
            except UnicodeDecodeError:
                try: return value.decode('gb18030')
                except UnicodeDecodeError: raise HTTPException(503, 'CLI 输出编码无法识别；不使用损坏文本') from None
        stdout, stderr = decode(proc.stdout), decode(proc.stderr)
        if raw: return proc.returncode, stdout+'\n'+stderr
        if proc.returncode:
            output=stdout+'\n'+stderr
            if any(s in output for s in ('API Key','Ziniao user is not logged in','CLIENT_LOGGED_OUT','UNAUTHORIZED','终端未绑定','账号不一致')):
                raise HTTPException(401,'紫鸟授权或登录状态异常，请在客户端处理后复检；未继续店铺操作')
            if 'CDP_ERROR' in output:
                raise HTTPException(504,'浏览器交互结果未确认；只允许检查预期控件是否已出现，不重复提交导出')
            raise HTTPException(503, '紫鸟请求失败；请检查连接或店铺会话，未继续操作')
        if '{' not in stdout:
            status_text=stdout+'\n'+stderr  # CLI shortcuts put human success lines on stderr when piped.
            confirmations = {('page','click'):'targetMatched=true', ('page','input'):'✓ 已输入', ('page','visit'):'✓ 页面已导航'}
            marker = confirmations.get(tuple(args[:2]))
            if marker and marker in status_text and '✗' not in status_text:
                return {'confirmed':True}  # Caller must still read back actual DOM state.
            raise HTTPException(503, '紫鸟未返回可确认的操作结果')
        try:
            # Some shortcuts print a success line before the JSON envelope.
            output = stdout[stdout.find('{'):]
            value = json.loads(output)
        except ValueError: raise HTTPException(503, '紫鸟返回格式异常，未继续操作') from None
        for _ in range(4):
            if not isinstance(value, dict): break
            if value.get('ok') is False: raise HTTPException(503, '紫鸟拒绝本次请求，未继续操作')
            if 'ok' in value and 'data' in value: value=value['data']
            else: break
        return value

    def check(self):
        try:
            code, output = self.run(['doctor'], raw=True)
            required = ['配置文件:', 'API Key 有效', '客户端登录用户:', 'ZClaw Bridge 连通正常']
            checks = {key: any('✓' in line and key in line for line in output.splitlines()) for key in required}
            warnings = [line.strip() for line in output.splitlines() if '⚠' in line]
            # Do not return raw doctor output (future versions may change key masking).
            ready = code == 0 and all(checks.values()) and not warnings and not any(c in output for c in ('✗', '❌'))
            return {'ready': ready, 'checks': checks, 'warning_count': len(warnings),
                    'message': '连接检查通过' if ready else ('请更新紫鸟客户端后复检终端绑定；尚未执行导出' if '不支持终端绑定' in output else '连接检查未全部通过，请在本机运行 ziniao-cli doctor 查看详情')}
        except HTTPException as exc:
            return {'ready': False, 'checks': {}, 'message': exc.detail}

    def profile(self, kinds=('settlement',), store_id=None):
        p = load_profile(self.selectors,store_id)
        if not p.get('reviewed') and not p.get('export_reviewed'):
            raise HTTPException(409, '导出页面、精确选择器和表头尚未实测审核；不会尝试模板选择器')
        for kind in kinds:
            r = p.get('reports', {}).get(kind, {})
            required = ('url', 'entry_selector', 'export_selector', 'history_rows',
                        'history_name', 'download_selector_template', 'schema')
            if any(not r.get(k) for k in required): raise HTTPException(409, '导出配方不完整，需要真实页面联调')
            url = urlsplit(r['url'])
            if url.scheme != 'https' or url.hostname not in p.get('allowed_hosts', []) or url.username or url.password:
                raise HTTPException(422, '报表 URL 不属于已审核的 HTTPS 店铺后台')
        if not p.get('identity_selector') or not p.get('expected_identity') or not p.get('challenge_selector'):
            raise HTTPException(409, '缺少店铺身份或登录验证定位规则')
        return p


    def collect(self, job, save, raw_dir, screenshot_dir):
        from ziniao_tiktok import collect
        return collect(self,job,save,raw_dir,screenshot_dir)
