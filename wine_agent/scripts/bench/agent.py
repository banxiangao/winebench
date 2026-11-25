"""agent.py - the benchmark's own code-writing agent (scenarios 3.x).

A mini-swe-agent style loop (model -> tool call -> observation -> model ...), but instead of a shell the model gets a
fixed tool set over a *read policy*: it can browse and search the whole source tree, except the tests and the original
implementation (the target function is served as a stub, its exclusive helpers are gone), it writes the function with
one tool, can compile the module, and submits.  No container: reads are served from the tree on disk, the file is
only touched (and restored) under a lock while compiling.

    ws  = Workspace(src, rec, cfg, wine)          # the agent's view of the tree for one record
    res = run_agent(model, run, system, task, ws, cfg)
    res: exit_status (Submitted | LimitsExceeded | TimeExceeded | RepeatedFormatError | ModelError ...), steps, usage,
         tool_counts, compiles, denied, history (the trajectory), code (what was written last, the submission)

[agent] settings (scenario config.toml): max_steps, max_tool_calls_per_step, wall_time_limit_seconds, max_format_errors,
read_max_lines, search_max_hits, list_max_entries, observation_max_chars, history_max_chars, tools, auto_compile_on_write,
require_compile_before_submit, submit_on_limit, max_compile_failures (N failed compiles end the run with the last version
as the submission; exit_status CompileLimit), deny_paths.
"""
import os, re, json, time, copy, fnmatch, threading, subprocess
from . import llm, report, csplice
from .hide import hide, stub

DENY_ALWAYS = ['*/tests', '*/tests/*', 'tests', 'tests/*', '.git', '.git/*', '*.orig', '*.rej']

TOOL_SCHEMAS = {
    'list_dir': dict(description='List a directory of the source tree (directories end with /). Paths are relative to the tree root.',
                     parameters={'type': 'object', 'properties': {'path': {'type': 'string', 'description': 'directory, e.g. "dlls/kernelbase" ("." = root)'}}, 'required': ['path']}),
    'read_file': dict(description='Read a range of lines of a file (numbered). At most read_max_lines lines per call; call again for more.',
                      parameters={'type': 'object', 'properties': {'path': {'type': 'string'}, 'start_line': {'type': 'integer', 'description': '1-based, default 1'},
                                                                  'end_line': {'type': 'integer', 'description': 'inclusive, default start_line + read_max_lines - 1'}}, 'required': ['path']}),
    'search': dict(description='Search the tree with a regular expression (grep -E); returns "path:line: text" hits. Use it to find definitions, callers, similar functions, .spec entries.',
                   parameters={'type': 'object', 'properties': {'pattern': {'type': 'string', 'description': 'extended regular expression'},
                                                               'path': {'type': 'string', 'description': 'directory or file to search, default "." (whole tree)'},
                                                               'glob': {'type': 'string', 'description': 'file name patterns, comma-separated, default "*.c,*.h,*.spec,*.idl,*.in"'}}, 'required': ['pattern']}),
    'write_function': dict(description='Write (or rewrite) your implementation: the complete C source of the target function with the given prototype, preceded by any static helper functions it needs. It replaces the stub in the target file. No #include lines, no prose.',
                           parameters={'type': 'object', 'properties': {'code': {'type': 'string'}}, 'required': ['code']}),
    'compile': dict(description='Compile the module with your current implementation (make of the module only, seconds). Returns OK or the compiler errors.',
                    parameters={'type': 'object', 'properties': {}}),
    'submit': dict(description='Finish: submit the implementation written with write_function. You cannot continue after this.',
                   parameters={'type': 'object', 'properties': {}}),
}

def tool_list(cfg):
    names = cfg.get('tools', list(TOOL_SCHEMAS))
    out = []
    for n in names:
        t = dict(TOOL_SCHEMAS[n]); d = t['description']
        if n == 'read_file': d = d.replace('read_max_lines', str(cfg.get('read_max_lines', 200)))
        out.append(dict(name=n, description=d, parameters=t['parameters']))
    return out

def _clip(text, n):
    if len(text) <= n: return text
    return text[:n // 2] + f'\n... [{len(text) - n} characters elided] ...\n' + text[-n // 2:]

# ---------------------------------------------------------------- the agent's view of the tree
class Workspace:
    def __init__(self, src, rec, cfg, wine=None, lock=None):
        self.src, self.rec, self.cfg, self.wine = os.path.abspath(src), rec, cfg, wine
        self.lock = lock or threading.Lock()
        f = rec['function']; self.rel = f['file']; self.name = f['name']; self.module = f['module']
        self.orig = open(os.path.join(self.src, self.rel), encoding='utf-8', errors='surrogateescape').read()
        self.hidden, self.hinfo = hide(self.orig, rec)
        self.stub_rec = stub_record(rec, self.hidden)
        self.view = self.hidden                    # what the agent sees of the target file (stub, later its own code)
        self.code = None; self.compiles = []; self.denied = []; self.tool_counts = {}
        self.deny = DENY_ALWAYS + list(cfg.get('deny_paths', []))

    def _denied(self, rel):
        r = rel.replace(os.sep, '/')
        return any(fnmatch.fnmatch(r, p) or fnmatch.fnmatch('/' + r, p) for p in self.deny)

    def _resolve(self, path):
        rel = os.path.normpath(path or '.').replace(os.sep, '/').lstrip('/')
        if rel.startswith('..'): raise ValueError(f'{path}: outside the source tree')
        if self._denied(rel) or rel == '.git':
            self.denied.append(rel); raise ValueError(f'{path}: not accessible (tests and version history are not part of this task)')
        full = os.path.join(self.src, rel)
        if not os.path.exists(full): raise ValueError(f'{path}: no such file or directory')
        return rel, full

    # ---- tools
    def list_dir(self, path='.'):
        rel, full = self._resolve(path)
        if not os.path.isdir(full): raise ValueError(f'{path}: not a directory')
        names = sorted(os.listdir(full)); out = []
        for n in names:
            r = (rel + '/' + n) if rel != '.' else n
            if self._denied(r) or n == '.git': continue
            out.append(n + '/' if os.path.isdir(os.path.join(full, n)) else n)
        mx = self.cfg.get('list_max_entries', 300)
        return '\n'.join(out[:mx]) + (f'\n... {len(out) - mx} more entries' if len(out) > mx else '') or '(empty)'

    def read_file(self, path, start_line=1, end_line=None):
        rel, full = self._resolve(path)
        if os.path.isdir(full): raise ValueError(f'{path}: is a directory (use list_dir)')
        text = self.view if rel == self.rel else open(full, encoding='utf-8', errors='replace').read()
        lines = text.split('\n'); n = len(lines); mx = self.cfg.get('read_max_lines', 200)
        s = max(1, int(start_line or 1)); e = min(n, int(end_line) if end_line else s + mx - 1, s + mx - 1)
        if s > n: raise ValueError(f'{path}: has only {n} lines')
        body = '\n'.join(f'{i:6}| {lines[i - 1]}' for i in range(s, e + 1))
        return f'{rel} lines {s}-{e} of {n}:\n{body}'

    def search(self, pattern, path='.', glob='*.c,*.h,*.spec,*.idl,*.in'):
        rel, full = self._resolve(path)
        try: re.compile(pattern)
        except re.error as e: raise ValueError(f'bad regular expression: {e}')
        mx = self.cfg.get('search_max_hits', 50)
        cmd = ['grep', '-rnIE', '--exclude-dir=tests', '--exclude-dir=.git'] + [f'--include={g.strip()}' for g in glob.split(',') if g.strip()] + ['--', pattern, rel]
        p = subprocess.run(cmd, cwd=self.src, capture_output=True, text=True, errors='replace', timeout=120)
        hits = []
        for l in p.stdout.split('\n'):
            if not l: continue
            if l.startswith('./'): l = l[2:]
            f = l.split(':', 1)[0]
            if self._denied(f): continue
            if f == self.rel: continue                                   # the target file is searched in the agent's view instead
            hits.append(l)
        if rel == '.' or self.rel.startswith(rel + '/') or rel == self.rel:
            for i, line in enumerate(self.view.split('\n'), 1):
                if re.search(pattern, line): hits.append(f'{self.rel}:{i}: {line}')
        hits.sort()
        if not hits: return 'no matches'
        return '\n'.join(h[:300] for h in hits[:mx]) + (f'\n... {len(hits) - mx} more hits (narrow the pattern or the path)' if len(hits) > mx else '')

    def write_function(self, code):
        chk = report.check(code, {'kind': 'code'}, self.name)
        if not chk['format_ok']:
            raise ValueError(f'the code must define {self.name} with the given prototype (plus optional static helpers) and have balanced braces; nothing else')
        new, info = csplice.splice(self.hidden, self.stub_rec, code)
        self.view, self.code = new, code
        start = new.find(code.strip()[:60]); line = new[:start].count('\n') + 1 if start >= 0 else '?'
        msg = f'written: {len(code.strip().splitlines())} lines into {self.rel} starting at line {line}'
        if info['added']: msg += f'; added: {", ".join(info["added"])}'
        if info['replaced']: msg += f'; replaced existing: {", ".join(info["replaced"])}'
        if info['dropped']: msg += f'; dropped (already defined in the file): {", ".join(info["dropped"])}'
        if self.cfg.get('auto_compile_on_write', False) and 'compile' in self.cfg.get('tools', TOOL_SCHEMAS): msg += '\n' + self.compile()
        return msg

    def compile(self):
        if self.code is None: raise ValueError('nothing to compile: call write_function first')
        if not self.wine: return 'compiling is not available in this run'
        full = os.path.join(self.src, self.rel)
        with self.lock:
            st = os.stat(full); outs = self.wine.outputs(self.rel, [self.module]); self.wine.snapshot(outs)   # clean .o / dll
            open(full, 'w', encoding='utf-8', errors='surrogateescape').write(self.view)
            try: c = self.wine.build_module(self.module)
            finally:                                                  # restore: old timestamp + saved outputs, no rebuild
                open(full, 'w', encoding='utf-8', errors='surrogateescape').write(self.orig)
                os.utime(full, ns=(st.st_atime_ns, st.st_mtime_ns)); self.wine.restore_snapshot(outs)
                if not self.wine.up_to_date(self.wine.module_targets(self.module)):
                    os.utime(full, None); self.wine.make(self.wine.module_targets(self.module))
        self.compiles.append(dict(ok=c['ok'], errors=len(c['errors']), seconds=c['seconds']))
        if c['ok']: return f'compiled OK ({self.module}, {c["seconds"]}s)'
        msg = 'compile FAILED:\n' + '\n'.join(c['errors'][:25] or [c['output_tail'][-1500:]])
        mx = self.cfg.get('max_compile_failures', 0)
        if mx and sum(1 for x in self.compiles if not x['ok']) >= mx:
            self.compile_limit = True
            msg += f'\n\nThis was compile attempt {mx} without success: the task ends here and your current version is submitted as it is.'
        return msg

    def submit(self):
        if self.code is None: raise ValueError('nothing to submit: write the function with write_function first')
        if self.cfg.get('require_compile_before_submit', False) and not (self.compiles and self.compiles[-1]['ok']):
            raise ValueError('the current implementation has not compiled successfully: call compile and fix the errors first')
        return 'submitted'

    def run_tool(self, name, args):
        """(observation text, finished)"""
        self.tool_counts[name] = self.tool_counts.get(name, 0) + 1
        if name not in self.cfg.get('tools', list(TOOL_SCHEMAS)) or not hasattr(self, name): return f'unknown tool {name}', False
        try:
            text = getattr(self, name)(**{k: v for k, v in (args or {}).items() if not k.startswith('_')})
            return text, name == 'submit' or getattr(self, 'compile_limit', False)
        except TypeError as e: return f'bad arguments for {name}: {e}', False
        except ValueError as e: return f'error: {e}', False
        except subprocess.TimeoutExpired: return 'error: the search took too long; narrow it', False

def stub_record(rec, hidden):
    """the record re-pointed at the stub in the hidden file (so csplice.splice can replace it)"""
    r = copy.deepcopy(rec); s = stub(rec); i = hidden.find(s)
    r['function']['code'] = s
    r['function']['start_line'] = hidden[:i].count('\n') + 1
    r['function']['end_line'] = r['function']['start_line'] + s.count('\n')
    return r

# ---------------------------------------------------------------- the loop
def _trim(history, max_chars):
    """keep the context bounded: the oldest tool outputs are replaced by a placeholder"""
    total = sum(len(h.get('content') or '') for h in history)
    for h in history:
        if total <= max_chars: break
        if h['role'] == 'tool' and len(h['content']) > 80:
            total -= len(h['content']) - 40; h['content'] = '[earlier output elided to save context]'

def run_agent(m, run, system, task, ws, cfg):
    tools = tool_list(cfg); history = [{'role': 'user', 'content': task}]
    usage = dict(prompt_tokens=0, completion_tokens=0); served = None; steps = 0; fmt_err = 0; t0 = time.time()
    status = None; error = None
    max_steps = cfg.get('max_steps', 40); per_step = cfg.get('max_tool_calls_per_step', 3); obs = cfg.get('observation_max_chars', 12000)
    while True:
        if steps >= max_steps: status = 'LimitsExceeded'; break
        if 0 < cfg.get('wall_time_limit_seconds', 0) <= time.time() - t0: status = 'TimeExceeded'; break
        msg, u, truncated, err = llm.complete_tools(m, run, system, history, tools)
        if err: status = 'ModelError'; error = err; break
        steps += 1
        usage['prompt_tokens'] += u.get('prompt_tokens') or 0; usage['completion_tokens'] += u.get('completion_tokens') or 0
        served = u.get('served_model') or served
        history.append(msg)
        if not msg['tool_calls']:
            fmt_err += 1
            if fmt_err >= cfg.get('max_format_errors', 3): status = 'RepeatedFormatError'; break
            history.append({'role': 'user', 'content': 'Your reply contained no tool call. Every reply must call exactly one tool; call submit when you are done.'
                            + (' (Your reply was cut off: be more concise.)' if truncated else '')})
            continue
        fmt_err = 0; done = False
        for k, t in enumerate(msg['tool_calls']):
            if done or k >= per_step: text = 'not executed: too many tool calls in one reply (one at a time)'
            else: text, done = ws.run_tool(t['name'], t['args'])
            history.append({'role': 'tool', 'tool_call_id': t['id'], 'name': t['name'], 'content': _clip(text, obs)})
        if done: status = 'CompileLimit' if getattr(ws, 'compile_limit', False) else 'Submitted'; break
        _trim(history, cfg.get('history_max_chars', 250000))
    submitted = status == 'Submitted' or (ws.code is not None and (status == 'CompileLimit' or (cfg.get('submit_on_limit', True) and status in ('LimitsExceeded', 'TimeExceeded', 'RepeatedFormatError'))))
    return dict(exit_status=status, error=error, steps=steps, usage=usage, served_model=served, seconds=round(time.time() - t0, 1),
                tool_counts=ws.tool_counts, compiles=ws.compiles, denied=ws.denied, hidden=ws.hinfo,
                code=ws.code if submitted else None, code_written=ws.code is not None, history=history)
