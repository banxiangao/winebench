"""Model calls.  complete(model, run, system, messages) -> (text, usage, truncated, error)
usage carries, besides the token counts, "served_model": the model id the API reports it actually used
(an alias such as "deepseek-chat" may be served by a newer model).

model = one [[models]] entry (provider, base_url, model, api_key_env, extra, ...)
run   = the [run] table merged with the model's own overrides (temperature, max_tokens, timeout_s)
Providers: "openai" (any OpenAI-compatible /chat/completions) and "anthropic" (/v1/messages).
To add one: write call_<name>(model, run, system, messages) and register it in PROVIDERS.
"""
import os, json, time, urllib.request, urllib.error

SECRETS = {}        # filled from secrets.toml by the caller

def api_key(m):
    """lookup order: api_key in the model block > secrets file > environment variable"""
    return m.get('api_key') or SECRETS.get(m['api_key_env']) or os.environ.get(m['api_key_env'], '')

def _post(url, headers, payload, timeout):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={'Content-Type': 'application/json', **headers})
    with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode())

# Per-model switches (in the [[models]] block), for APIs that reject the standard fields:
#   send_temperature = false                      -> no "temperature" in the request (newer Claude / OpenAI reasoning models reject it)
#   max_tokens_field = "max_completion_tokens"    -> name of the output cap field (OpenAI's current models want this one)
# Both are also switched on automatically the first time an API answers 400 complaining about the field.
def call_openai(m, run, system, messages):
    body = dict(model=m['model'], messages=[{'role': 'system', 'content': system}] + messages)
    if m.get('send_temperature', True): body['temperature'] = run.get('temperature', 0.0)
    if run.get('max_tokens'): body[m.get('max_tokens_field', 'max_tokens')] = run['max_tokens']   # 0 / unset = provider default (no explicit cap)
    body.update(m.get('extra', {}))                                             # e.g. response_format
    r = _post(m['base_url'].rstrip('/') + '/chat/completions', {'Authorization': f'Bearer {api_key(m)}'}, body, run.get('timeout_s', 180))
    c = r['choices'][0]
    # reasoning models put their thinking in message.reasoning_content and may return no "content" at all when
    # the cap is hit while still thinking (that is how a tiny probe looks on MiniMax-M3 / GLM-5.3)
    text = c.get('message', {}).get('content') or ''
    return text, dict(r.get('usage', {}), served_model=r.get('model')), c.get('finish_reason') == 'length' or not text

def call_anthropic(m, run, system, messages):
    body = dict(model=m['model'], system=system, messages=messages,
                max_tokens=run.get('max_tokens') or run.get('anthropic_default_max_tokens', 16000))   # the field is mandatory
    if m.get('send_temperature', True): body['temperature'] = run.get('temperature', 0.0)
    body.update(m.get('extra', {}))
    r = _post(m['base_url'].rstrip('/') + '/v1/messages', {'x-api-key': api_key(m), 'anthropic-version': '2023-06-01'}, body, run.get('timeout_s', 180))
    u = r.get('usage', {})
    return ''.join(b.get('text', '') for b in r.get('content', [])), \
           dict(prompt_tokens=u.get('input_tokens'), completion_tokens=u.get('output_tokens'), served_model=r.get('model')), \
           r.get('stop_reason') == 'max_tokens'

PROVIDERS = {'openai': call_openai, 'anthropic': call_anthropic}

def run_settings(scn_run, m):
    """[run] of the scenario with the model's own overrides"""
    return {**scn_run, **{k: m[k] for k in ('temperature', 'max_tokens', 'timeout_s') if k in m}}

def _adapt(m, err):
    """a 400 about temperature / max_tokens: switch the model block (shared by all workers) and say so once"""
    if 'temperature' in err and m.get('send_temperature', True):
        m['send_temperature'] = False; fix = 'send_temperature = false'
    elif 'max_completion_tokens' in err and m.get('max_tokens_field', 'max_tokens') != 'max_completion_tokens':
        m['max_tokens_field'] = 'max_completion_tokens'; fix = 'max_tokens_field = "max_completion_tokens"'
    else: return False
    print(f'[{m["name"]}] API rejected a field; using {fix} from now on (add it to the [[models]] block to silence this)', flush=True)
    return True

def complete(m, run, system, messages):
    """call with retries; returns (text, usage, truncated, error)"""
    err = None; attempt = 0; adapted = 0; wait = 2
    while attempt < run.get('max_retries', 3):
        try:
            text, usage, truncated = PROVIDERS[m['provider']](m, run, system, messages)
            return text, usage, truncated, None
        except urllib.error.HTTPError as e:
            err = f'HTTP {e.code}: {e.read().decode(errors="ignore")[:300]}'
            if e.code == 400 and adapted < 2 and _adapt(m, err): adapted += 1; continue   # field rejected: model block fixed, retry at once (not counted)
            if e.code in (400, 401, 403, 404): break                               # not worth retrying
            if e.code == 429: wait = 30                                            # rate limit: back off for real (30, 60, 90 s)
        except Exception as e: err = f'{type(e).__name__}: {e}'
        attempt += 1; time.sleep(wait * attempt)
    return '', {}, False, err

def probe(m, run):
    """one tiny request: (served model id, error)"""
    text, usage, _, err = complete(m, dict(run, max_tokens=8, max_retries=1), 'Reply with the single word: ok', [{'role': 'user', 'content': 'ok?'}])
    return usage.get('served_model'), err

def usable(m):
    """why a model will be skipped, or None"""
    if not m.get('enabled', True): return 'enabled = false'
    if m['provider'] not in PROVIDERS: return f'unknown provider {m["provider"]}'
    if not api_key(m): return f'no key ({m["api_key_env"]} not in secrets.toml or environment)'
    return None
