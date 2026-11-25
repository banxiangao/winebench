"""Checking replies and summarising a responses directory."""
import os, re, json, glob

CODE_LEAK = re.compile(r'```|^\s*(#include|return\s+\w|if\s*\(|for\s*\(|while\s*\(|\w+\s*\*?\s*\w+\s*=\s*\w+\s*\(.*\);)\s*$', re.M)

def parse_reply(text, headings):
    """headings == []: JSON mode, return the first {...} object; else split into the required sections"""
    if not headings:
        m = re.search(r'\{.*\}', text.strip(), re.S)
        try: return json.loads(m.group(0)) if m else None
        except json.JSONDecodeError: return None
    pos = [(text.find(h), h) for h in headings]
    if any(i < 0 for i, _ in pos): return None
    pos.sort(); out = {}
    for k, (i, h) in enumerate(pos):
        end = pos[k + 1][0] if k + 1 < len(pos) else len(text)
        out[h.lstrip('# ').strip()] = text[i + len(h):end].strip()
    return out

def code_leak(text, json_mode):
    """True if the reply contains code (a rule violation for the architect)"""
    body = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip()) if json_mode else text    # a ```json fence is fine
    return bool(CODE_LEAK.search(body))

FENCE = re.compile(r'^\s*```[a-zA-Z]*\s*\n(.*?)\n\s*```\s*$', re.S)
OPEN_FENCE = re.compile(r'^\s*```[a-zA-Z]*\s*\n')
def extract_code(text, function_name):
    """reply_format = "code": the reply must be C source defining `function_name`.
    A single surrounding fence is tolerated and stripped; anything else around the code is not."""
    t = text.strip(); m = FENCE.match(t)
    if m: t = m.group(1)
    elif OPEN_FENCE.match(t) and '```' not in OPEN_FENCE.sub('', t, count=1):   # opening fence, the model stopped before closing it
        t = OPEN_FENCE.sub('', t, count=1).strip()
    if '```' in t: return None                                              # prose + several code blocks
    if not re.search(r'\b' + re.escape(function_name) + r'\s*\(', t): return None
    bare = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', '', t, flags=re.S)   # drop comments and literals
    if bare.count('{') == 0 or bare.count('{') != bare.count('}'): return None
    return t

def check(text, fmt, function_name=''):
    """fmt = {"kind": "json"|"headings"|"code", "headings": [...]} -> parsed / format_ok / code_leak"""
    if not text: return dict(parsed=None, format_ok=False, code_leak=None)
    if fmt.get('kind') == 'code':
        code = extract_code(text, function_name)
        return dict(parsed={'code': code} if code else None, format_ok=code is not None, code_leak=None)
    headings = fmt.get('headings', [])
    parsed = parse_reply(text, headings)
    return dict(parsed=parsed, format_ok=parsed is not None, code_leak=code_leak(text, not headings))

def is_bad(r):
    return bool(r.get('error') or r.get('truncated') or not r.get('format_ok'))

def status_line(r):
    if r.get('error'): return 'ERR ' + r['error'][:60]
    s = 'ok' if r['format_ok'] else 'bad-format'
    if r.get('truncated'): s += ' TRUNCATED (raise max_tokens)'
    if r.get('code_leak'): s += ' CODE-LEAK'
    return s

def summarize(model_dir):
    rs = [json.load(open(f)) for f in glob.glob(os.path.join(model_dir, '[0-9][0-9][0-9][0-9].json'))]   # not the <id>.attemptN.json history
    s = dict(model=os.path.basename(model_dir), model_id=sorted({r.get('model_id') for r in rs if r.get('model_id')}),
             served_model=sorted({r.get('served_model') for r in rs if r.get('served_model')}),
             total=len(rs), errors=sum(1 for r in rs if r.get('error')),
             format_ok=sum(1 for r in rs if r.get('format_ok')), truncated=sum(1 for r in rs if r.get('truncated')),
             code_leak=sum(1 for r in rs if r.get('code_leak')),
             first_try_ok=sum(1 for r in rs if r.get('format_ok') and not r.get('truncated') and r.get('attempts', 1) == 1),
             retried=sum(1 for r in rs if r.get('attempts', 1) > 1),
             prompt_tokens=sum((r.get('usage') or {}).get('prompt_tokens') or 0 for r in rs),
             completion_tokens=sum((r.get('usage') or {}).get('completion_tokens') or 0 for r in rs))
    json.dump(s, open(os.path.join(model_dir, 'summary.json'), 'w'), indent=1)
    return s
