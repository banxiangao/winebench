"""csplice.py - put a programmer model's C code into the Wine source file of the function it re-implements.

    new_source, info = splice(original_source, record, llm_code)

  - the target function (record["function"]) is replaced by the model's definition of it
  - every other function the model defined: if the file already has a function of that name it is replaced in place,
    otherwise it is inserted, in the model's order, right before the target function
  - #include lines the model added go after the file's last #include (lines already present are dropped)
  - macros / types / globals / prototypes the model added are kept unless the file already defines that name
    (then they are dropped, to avoid redefinition errors)
  info = {"replaced": [...], "added": [...], "dropped": [...], "includes_added": [...], "kept_pp": n}
SpliceError: the model's code does not define the target function, or the original function text is not where the
record says (source tree does not match the dataset).

Also: normalize(code) and similarity(a, b) for the "identical to the original" metric.
"""
import re, difflib

class SpliceError(Exception): pass

KEYWORDS = {'if', 'for', 'while', 'switch', 'return', 'sizeof', 'else', 'do', 'case'}
IDENT = r'[A-Za-z_]\w*'

# ---------------------------------------------------------------- lexical helpers
def _scan(src, literals):
    """src with comments blanked (newlines kept, so offsets and line numbers are unchanged);
    literals=True also blanks the inside of string / char literals (so braces can be counted)"""
    out = []; i = 0; n = len(src)
    while i < n:
        c = src[i]
        if src.startswith('/*', i):
            j = src.find('*/', i + 2); j = n if j < 0 else j + 2
            out.append(''.join('\n' if ch == '\n' else ' ' for ch in src[i:j])); i = j
        elif src.startswith('//', i):
            j = src.find('\n', i); j = n if j < 0 else j
            out.append(' ' * (j - i)); i = j
        elif c in '"\'':
            j = i + 1
            while j < n and src[j] != c and src[j] != '\n':
                j += 2 if src[j] == '\\' else 1
            j = min(j + 1, n); s = src[i:j]
            out.append(s[0] + ' ' * (len(s) - 2) + s[-1] if literals and len(s) >= 2 else s); i = j
        else:
            out.append(c); i += 1
    return ''.join(out)

def mask(src): return _scan(src, True)

def _line_start(m, i):
    """True if only blanks precede position i on its line"""
    k = i - 1
    while k >= 0 and m[k] in ' \t': k -= 1
    return k < 0 or m[k] == '\n'

def _pp_end(m, i):
    """end (after the newline) of the preprocessor line starting at i, following backslash continuations"""
    n = len(m)
    while True:
        e = m.find('\n', i)
        if e < 0: return n
        if e > 0 and m[e - 1] == '\\': i = e + 1; continue
        return e + 1

def _match_brace(m, i):
    """index of the } matching the { at i (preprocessor lines inside are skipped); -1 if unbalanced"""
    depth = 0; n = len(m)
    while i < n:
        c = m[i]
        if c == '#' and _line_start(m, i): i = _pp_end(m, i); continue
        if c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0: return i
        i += 1
    return -1

def _strip_attrs(h):
    """drop trailing __attribute__((...)) groups; return (head, name) where name is the function name or None"""
    while True:
        h = h.rstrip()
        if not h.endswith(')'): return h, None
        depth = 0; k = len(h) - 1
        while k >= 0:
            if h[k] == ')': depth += 1
            elif h[k] == '(':
                depth -= 1
                if depth == 0: break
            k -= 1
        if k < 0: return h, None
        before = h[:k].rstrip()
        mm = re.search(IDENT + r'$', before)
        if not mm: return h, None
        word = mm.group(0)
        if word == '__attribute__' or word.startswith('__attribute'): h = before[:mm.start()]; continue
        return h, word

def _is_function_head(h):
    """h = masked text before a top-level '{' ; returns the function name or None"""
    h = h.strip()
    if not h: return None
    depth = 0
    for c in h:                                                     # '=' outside parentheses -> an initializer, not a function
        if c == '(': depth += 1
        elif c == ')': depth -= 1
        elif c == '=' and depth == 0: return None
    head, name = _strip_attrs(h)
    if not name or name in KEYWORDS: return None
    if re.match(r'(typedef|struct|union|enum)\b', head) and '(' not in head: return None
    return name

def _decl_name(d):
    """kind, name of a top-level declaration (masked text, without the trailing ';')"""
    d = d.strip()
    if d.startswith('#'):
        mm = re.match(r'#\s*(\w+)\s*(.*)', d, re.S)
        if not mm: return 'pp', None
        if mm.group(1) == 'include': return 'include', re.sub(r'\s+', ' ', mm.group(2).strip())
        if mm.group(1) == 'define':
            nm = re.match(IDENT, mm.group(2)); return 'macro', nm.group(0) if nm else None
        return 'pp', None
    body = d[:-1].rstrip() if d.endswith(';') else d
    if body.startswith('typedef'):
        after = body[body.rfind('}') + 1:] if '}' in body else body
        mm = re.search(r'\(\s*\*\s*(' + IDENT + r')\s*\)', after)
        if mm: return 'typedef', mm.group(1)
        ids = re.findall(IDENT, after.split('[')[0])
        return 'typedef', ids[-1] if ids else None
    mm = re.match(r'(?:(?:static|extern|const)\s+)*(struct|union|enum)\s+(' + IDENT + r')\s*(\{|$)', body)
    if mm: return 'tag', mm.group(2)
    if '{' not in body and body.endswith(')'):
        _, name = _strip_attrs(body)
        if name: return 'proto', name
    ids = re.findall(IDENT, re.split(r'[=\[{]', body)[0])
    return 'global', ids[-1] if ids else None

# ---------------------------------------------------------------- top-level items
def items(src, skip=None):
    """top-level items of a C file: dict(kind, name, start, code_start, end, text)
    kind: func | include | macro | pp | typedef | tag | proto | global
    start = beginning of the item including comments before it, code_start = first code character
    skip = (start, end) span to leave out of the scan (the target function, whose extent the record already gives)"""
    m = mask(src); n = len(src); out = []; i = 0; chunk = 0
    if skip: m = m[:skip[0]] + ''.join('\n' if c == '\n' else ' ' for c in m[skip[0]:skip[1]]) + m[skip[1]:]
    def emit(kind, name, end):
        nonlocal chunk
        cs = chunk
        while cs < end and m[cs].isspace(): cs += 1
        st = chunk
        while st < cs and src[st].isspace(): st += 1
        out.append(dict(kind=kind, name=name, start=st, code_start=cs, end=end, text=src[st:end])); chunk = end
    while i < n:
        c = m[i]
        if c == '#' and _line_start(m, i):
            e = _pp_end(m, i)
            if m[chunk:i].strip() == '':                            # a directive of its own
                kind, name = _decl_name(src[i:e]); emit(kind, name, e)      # raw text: the include name is a literal
            i = e; continue
        if c == ';':
            if m[chunk:i].strip(): kind, name = _decl_name(m[chunk:i + 1]); emit(kind, name, i + 1)
            else: chunk = i + 1
            i += 1; continue
        if c == '{':
            close = _match_brace(m, i)
            if close < 0: break
            name = _is_function_head(m[chunk:i])
            if name: emit('func', name, close + 1)
            i = close + 1; continue                                 # not a function: keep accumulating up to the ';'
        i += 1
    return out

# ---------------------------------------------------------------- splicing
def _target_span(src, rec):
    """(start, end) offsets of the original function in src, checked against the record's code"""
    f = rec['function']; code = f['code'].rstrip('\n')
    lines = src.split('\n')
    s, e = f['start_line'] - 1, f['end_line']
    cand = '\n'.join(lines[s:e]).rstrip('\n')
    if cand == code:
        start = sum(len(l) + 1 for l in lines[:s]); return start, start + len(cand)
    if src.count(code) == 1:                                          # line numbers off (other edits?) but text unique
        start = src.find(code); return start, start + len(code)
    raise SpliceError(f'original code of {f["name"]} not found at {f["file"]}:{f["start_line"]}-{f["end_line"]}')

def splice(src, rec, llm_code):
    target = rec['function']['name']
    t_start, t_end = _target_span(src, rec)
    orig = items(src, (t_start, t_end))
    o_funcs = {it['name']: it for it in orig if it['kind'] == 'func'}
    o_names = {it['name'] for it in orig if it['kind'] in ('macro', 'typedef', 'tag', 'global', 'proto') and it['name']}
    o_incl = {it['name'] for it in orig if it['kind'] == 'include'}
    info = dict(replaced=[], added=[], dropped=[], includes_added=[], kept_pp=0)
    block = []; repl = []; incl = []; target_text = None
    for it in items(llm_code):
        k, nm = it['kind'], it['name']
        if k == 'func':
            if nm == target: target_text = it['text']
            elif nm in o_funcs: repl.append((o_funcs[nm], it['text'])); info['replaced'].append(nm)
            else: block.append(it['text']); info['added'].append(nm)
        elif k == 'include':
            if nm not in o_incl: incl.append(it['text'].rstrip('\n')); info['includes_added'].append(nm)
        elif k == 'pp':
            block.append(it['text']); info['kept_pp'] += 1
        elif nm and nm in o_names: info['dropped'].append(f'{k} {nm}')
        else: block.append(it['text']); info['added'].append(f'{k} {nm}')
    if target_text is None: raise SpliceError(f'the reply does not define {target}')
    block.append(target_text)
    new = src[:t_start] + '\n\n'.join(t.rstrip('\n') for t in block) + src[t_end:]
    for it, text in repl:                                            # by text, so earlier edits do not shift anything
        old = src[it['code_start']:it['end']]
        if new.count(old) != 1: raise SpliceError(f'cannot replace helper {it["name"]} (definition not unique)')
        new = new.replace(old, text)
    if incl:
        last = [it for it in orig if it['kind'] == 'include' and it['start'] < t_start]
        if last:
            anchor = last[-1]['text']
            if new.count(anchor) != 1: raise SpliceError('cannot place the added #include lines')
            pos = new.find(anchor) + len(anchor)
        else: pos = 0
        new = new[:pos] + '\n'.join(incl) + '\n' + new[pos:]
    return new, info

# ---------------------------------------------------------------- "identical" metric
def normalize(code):
    """comments removed, whitespace collapsed, no space around punctuation (literals kept as written)"""
    s = re.sub(r'\s+', ' ', _scan(code, False)).strip()
    return re.sub(r'\s*([{}()\[\];,=+\-*/<>!&|^%?:])\s*', r'\1', s)

def similarity(a, b):
    return round(difflib.SequenceMatcher(None, normalize(a), normalize(b), autojunk=False).ratio(), 4)

def target_code(llm_code, name):
    """the model's definition of `name` alone (for the identical / similarity metrics)"""
    for it in items(llm_code):
        if it['kind'] == 'func' and it['name'] == name: return llm_code[it['code_start']:it['end']]
    return None
