from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import re
import json
import time
import random
from config import COOKIES, UMID_TOKEN

app = Flask(__name__)
CORS(app)

BASE_URL = 'https://tm-api.aliyun.com/trademarksearch/search'

HEADERS = {
    'accept': '*/*',
    'accept-language': 'zh-CN,zh;q=0.9',
    'referer': 'https://tm.aliyun.com/channel/search?accounttraceid=9fa7af3cb5dd4a698d104e3a6ea22bd4fzjj',
    'sec-ch-ua': '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
    'sec-ch-ua-mobile': '?0',
    'sec-ch-ua-platform': '"macOS"',
    'sec-fetch-dest': 'script',
    'sec-fetch-mode': 'no-cors',
    'sec-fetch-site': 'same-site',
    'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36',
    'Cookie': COOKIES,
}

TARGET_CODES = {'35', '41', '42'}
CLASS_NAMES = {'35': '广告销售', '41': '教育娱乐', '42': '网站服务'}


def parse_jsonp(text):
    """从 JSONP 响应中提取 JSON 数据，直接截取第一个 { 到最后一个 } """
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and start < end:
        return json.loads(text[start:end + 1])
    return None


def is_blocked(text):
    """检测是否触发了阿里反爬惩罚页"""
    return 'punishPath' in text or '_____tmd_____' in text


def query_trademark(name):
    """调用阿里云商标查询接口，返回 (data, raw_text)"""
    callback = f'jsonp_{int(time.time() * 1000)}_{random.randint(10000, 99999)}'
    params = {
        'keyword': name,
        'searchType': 'ALL',
        'pageNum': '1',
        'pageSize': '0',
        'searchResultType': 'AGGREGATION',
        'umidToken': UMID_TOKEN,
        'callback': callback,
    }
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
    resp.raise_for_status()
    raw = resp.text
    print(f'[{name}] status={resp.status_code} body_prefix={raw[:120]}')
    return parse_jsonp(raw), raw


# 调试接口：返回原始响应，方便排查 Cookie 失效等问题
@app.route('/api/debug', methods=['GET'])
def debug():
    keyword = request.args.get('keyword', '测试')
    callback = f'jsonp_{int(time.time() * 1000)}_{random.randint(10000, 99999)}'
    params = {
        'keyword': keyword,
        'searchType': 'ALL',
        'pageNum': '1',
        'pageSize': '0',
        'searchResultType': 'AGGREGATION',
        'umidToken': UMID_TOKEN,
        'callback': callback,
    }
    try:
        resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=15)
        return jsonify({
            'status_code': resp.status_code,
            'content_type': resp.headers.get('Content-Type'),
            'body_preview': resp.text[:500],
            'parsed': parse_jsonp(resp.text) is not None,
        })
    except Exception as e:
        return jsonify({'error': str(e)})


def analyze(name):
    """分析单个商标名的风险"""
    try:
        data, raw = query_trademark(name)

        if is_blocked(raw):
            return {'name': name, 'error': '触发反爬限制，请稍后重试或减少批量数量'}

        if not data:
            return {'name': name, 'error': 'JSONP 解析失败'}

        if str(data.get('code')) != '200':
            return {'name': name, 'error': f"接口返回: code={data.get('code')} message={data.get('message')}"}

        cls_list = data.get('data', {}).get('stat', {}).get('clsAggList', [])
        status_map = {
            item['code']: item['status']
            for item in cls_list
            if item['code'] in TARGET_CODES
        }

        all_zero = all(status_map.get(code) == '0' for code in TARGET_CODES)

        return {
            'name': name,
            'risk': 'low' if all_zero else 'high',
            'details': {code: status_map.get(code, '-') for code in sorted(TARGET_CODES)},
        }

    except requests.exceptions.Timeout:
        return {'name': name, 'error': '请求超时'}
    except Exception as e:
        return {'name': name, 'error': str(e)}


@app.route('/api/check', methods=['POST'])
def check():
    body = request.get_json()
    raw = body.get('names', '')

    names = [n.strip() for n in re.split(r'[\s\n]+', raw) if n.strip()]

    if not names:
        return jsonify({'error': '请输入至少一个名称'}), 400

    # 单次最多查 20 个，避免超时和触发反爬
    if len(names) > 20:
        return jsonify({'error': f'单次最多查询 20 个，当前输入 {len(names)} 个，请分批查询'}), 400

    results = []
    for i, name in enumerate(names):
        results.append(analyze(name))
        if i < len(names) - 1:
            # 随机延迟 1~2 秒，降低触发反爬概率
            time.sleep(random.uniform(1, 2))

    return jsonify(results)


if __name__ == '__main__':
    app.run(debug=True, port=5001)
