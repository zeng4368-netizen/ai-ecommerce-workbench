import importlib.util
import io
from pathlib import Path
import pandas as pd
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workbench_server', ROOT / 'server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)


def test_persistence_and_validation(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DB', tmp_path / 'test.sqlite3')
    client = TestClient(server.app)
    assert client.get('/api/health').json()['storage'] == 'SQLite'
    assert client.get('/api/tasks').json() == {'tasks': {}}
    assert client.put('/api/tasks', json={'tasks': {'test': 'doing'}}).status_code == 200
    assert client.get('/api/tasks').json()['tasks']['test'] == 'doing'
    assert client.put('/api/tasks', json={'tasks': {'test': 'bad'}}).status_code == 422
    assert client.put('/api/tasks', json={'tasks': {}}, headers={'Origin': 'https://outside.invalid'}).status_code == 403
    assert client.get('/api/results/not-a-job').status_code == 404
    assert client.get('/.env').status_code == 404


def test_local_model_endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(server, 'DB', tmp_path / 'analysis.sqlite3')
    client = TestClient(server.app)
    monkeypatch.delenv('WORKBENCH_LLM_MODEL', raising=False)
    assert client.post('/api/analyze', json={'prompt': 'Test'}).status_code == 503
    monkeypatch.setenv('WORKBENCH_LLM_MODEL', 'test-model')
    monkeypatch.setenv('WORKBENCH_LLM_BASE_URL', 'https://external.invalid/v1')
    assert client.post('/api/analyze', json={'prompt': 'Test'}).status_code == 422
    monkeypatch.setenv('WORKBENCH_LLM_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.setenv('WORKBENCH_LLM_API_KEY', 'test-secret-do-not-use')
    assert client.get('/api/health').json()['provider'] == 'api.deepseek.com'
    assert 'test-secret' not in client.get('/api/health').text
    monkeypatch.setattr(server, 'local_model', lambda prompt: {'content': '本地模型测试回复', 'mode': 'local_model', 'model': 'test', 'usage': {}, 'provider': 'localhost'})
    result = client.post('/api/analyze', json={'prompt': 'Test'}).json()
    assert result['mode'] == 'local_model'
    assert result['content'] == '本地模型测试回复'
    assert len(result['evidence_sha256']) == 64
    assert client.get('/api/analyses').json()['analyses'][0]['id'] == result['id']
    assert 'prompt' not in client.get('/api/analyses').json()['analyses'][0]
    assert client.get('/api/analyses/' + result['id']).json()['prompt'] == 'Test'
    assert client.get('/api/analyses/missing').status_code == 404


def test_provider_errors_are_safe(monkeypatch):
    monkeypatch.setenv('WORKBENCH_LLM_MODEL', 'test')
    monkeypatch.setenv('WORKBENCH_LLM_BASE_URL', 'https://api.deepseek.com')
    monkeypatch.setenv('WORKBENCH_LLM_API_KEY', 'test-secret')
    class Opener:
        def open(self, request, timeout):
            raise server.urllib.error.HTTPError(request.full_url, 402, 'test-secret', {}, None)
    monkeypatch.setattr(server.urllib.request, 'build_opener', lambda *args: Opener())
    response = TestClient(server.app).post('/api/analyze', json={'prompt': 'Test'})
    assert response.status_code == 502
    assert '余额不足' in response.text
    assert 'test-secret' not in response.text
    for address in ['http://api.deepseek.com', 'https://api.deepseek.com.evil.invalid', 'https://api.deepseek.com@evil.invalid', 'https://api.deepseek.com/path', 'https://api.deepseek.com?key=foo']:
        monkeypatch.setenv('WORKBENCH_LLM_BASE_URL', address)
        assert TestClient(server.app).get('/api/health').json()['llm'] == 'not_configured'


def test_question_system_prompt_is_not_a_report_template(monkeypatch):
    monkeypatch.setenv('WORKBENCH_LLM_MODEL', 'test')
    monkeypatch.setenv('WORKBENCH_LLM_BASE_URL', 'http://127.0.0.1:11434/v1')
    bodies=[]
    class Response:
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def read(self,n): return b'{"choices":[{"message":{"content":"answer"},"finish_reason":"stop"}]}'
    class Opener:
        def open(self,request,timeout):
            import json
            bodies.append(json.loads(request.data));return Response()
    monkeypatch.setattr(server.urllib.request,'build_opener',lambda *args:Opener())
    server.local_model('哪款产品日销下降？')
    system=bodies[-1]['messages'][0]['content']
    assert '用户的问题决定回答范围' in system
    assert '每项行动有商品/SKU' not in system
    server.local_model('JSON action plan',structured=True)
    assert bodies[-1]['response_format']=={'type':'json_object'}


def test_original_cleaner_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA', tmp_path)
    client = TestClient(server.app)
    mapping = '店名,店编,国家,初级,中级,储高/见高,CEO\n测试店,SHOP001,MY,A,B,C,D\n'.encode('utf-8-sig')
    ads = ('Cost,Creative type,Time posted,Product ad click rate,Ad conversion rate\n'
           '10,Video,2026-09-05,0.02,0.03\n'
           '20,Video,2026-08-20,0.04,0.05\n'
           '0,Video,2026-09-06,0.90,0.90\n').encode('utf-8-sig')
    response = client.post('/api/clean', data={'start_date': '2026-09-01'},
                           files=[('mapping', ('mapping.csv', mapping, 'text/csv')),
                                  ('ads', ('SHOP001.csv', ads, 'text/csv'))])
    assert response.status_code == 200, response.text
    workbook = client.get(response.json()['download'])
    assert workbook.status_code == 200
    df = pd.read_excel(io.BytesIO(workbook.content))
    assert list(df.columns) == ['店名','店编','国家','初级','中级','储高/见高','CEO','L7D新建素材数','L7D新建素材消耗额','总素材数','总消耗','L7D CTR','L7D CVR','总CTR','总CVR']
    row = df.iloc[0]
    assert row['总素材数'] == 2
    assert row['总消耗'] == 30
    assert row['L7D新建素材数'] == 1
    assert row['L7D新建素材消耗额'] == 10
    assert row['总CTR'] == 3
    assert row['L7D CTR'] == 2
