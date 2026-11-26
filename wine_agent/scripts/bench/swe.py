"""swe.py - what the off-the-shelf agents (mini-swe-agent, OpenHands) share: the restricted Wine trees they work in,
the per-task setup, the patch they hand back, and the rule checks.

A worker tree (scripts/make_swe_trees.sh) is a copy of the Wine source WITHOUT .git and WITHOUT the test sources
(dlls/*/tests and programs/*/tests keep only their Makefile.in, so the build still works but no test can be built or
run), turned into a fresh git repository whose first commit is the clean tree; plus a copy of the build directory with
every test binary removed.  For one task:

    tree.setup(rec)      reset to the clean commit, write the hidden file (stub + exclusive helpers removed, bench/hide.py),
                         write ./compile, drop the module's objects of that file from the build copy (so the original
                         binary is not there either), commit "task <id>" -> `git diff` afterwards shows only the agent's work
    tree.patch()         the agent's changes as a unified diff (new files included), ready for evaluate.py (reply_format = "patch")
    tree.violations(commands)   commands that reach outside the rules (paths outside the tree, tests, wine, make test, ...)
"""
import os, re, json, shlex, shutil, subprocess, glob, fcntl, time, threading
from .hide import hide
from .prompt import build_targets

RULES_RE = [                                    # (name, regex over one shell command) - reported, not blocked
    ('tests',         r'(^|[\s/"\'])tests?/|/tests?([\s/"\']|$)|\.ok\b|winetest|_test\.exe|\bmake\b.*\btest\b'),
    ('outside_tree',  r'(^|[\s"\'=])(/home/|/root/|~/|\.\./|/scratch/|/project/|/w/|/t/|/media/|/mnt/)'),
    ('dataset',       r'wine500|wine_agent|wine_bench|/dataset/'),
    ('runs_wine',     r'(^|[\s/;&|])(wine|wine64|wineserver|wineboot)\b'),
    ('git_history',   r'\bgit\s+(log|show|checkout|reset|stash|reflog|diff\s+HEAD~|revert|init|commit|gc|restore)\b|(^|[\s/])\.git([\s/;&|]|$)'),
    ('network',       r'\b(curl|wget|pip|git\s+clone|apt)\b'),
]

def sh(cmd, cwd, timeout=600, check=True):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, errors='replace', timeout=timeout)
    if check and p.returncode: raise RuntimeError(f'{" ".join(cmd)} failed in {cwd}:\n{p.stdout}{p.stderr}'[-2000:])
    return p.stdout

class SweTree:
    """one restricted source + build pair (scripts/make_swe_trees.sh); one agent run at a time"""
    def __init__(self, src, build, jobs=4, name='w0'):
        self.src, self.build, self.jobs, self.name = os.path.abspath(src), os.path.abspath(build), jobs, name
        # the repository lives OUTSIDE the tree (<src>.gitdir): an agent that deletes or re-initialises .git cannot destroy it
        # (it happened: `rm -rf .git` killed a tree and the whole run).  The tree keeps a .git FILE pointing there, so git
        # still works for the agent as before; our own git calls name the directory explicitly and do not depend on it.
        # What the agent sees through .git is a third thing, <src>.taskgit: a repository with ONE parentless commit (the task as
        # handed out) that borrows its objects from <src>.gitdir.  git status / diff work, but HEAD~1, git log and the reflog do
        # not lead to the clean commit, i.e. to the original of the function (it was taken that way: `git show <base>:file`).
        self.gitdir = self.src + '.gitdir'; self.taskgit = self.src + '.taskgit'; dot = os.path.join(self.src, '.git')
        if os.path.isdir(dot) and not os.path.isdir(self.gitdir): shutil.move(dot, self.gitdir)       # trees made before this change
        if not os.path.isdir(self.gitdir): raise SystemExit(f'{self.src}: not a swe tree (no repository): run scripts/make_swe_trees.sh')
        if not os.path.exists(os.path.join(self.build, 'Makefile')): raise SystemExit(f'{self.build}: no Makefile')
        if glob.glob(os.path.join(self.src, 'dlls', '*', 'tests', '*.c')): raise SystemExit(f'{self.src}: test sources present: not a swe tree')
        self._lock = open(os.path.join(self.build, '.swe.lock'), 'a+')         # one agent runner per tree pair at a time
        try: fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            import errno
            if e.errno in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EACCES):     # really held by somebody else
                self._lock.seek(0); who = self._lock.read().strip()
                raise SystemExit(f'{self.src} is in use by another agent run ({who or "unknown"}): wait for it, or make more trees (make_swe_trees.sh)')
            print(f'note: {self.build}: file locks are not supported on this filesystem ({e}); continuing without the lock', flush=True)
        self._lock.seek(0); self._lock.truncate(); self._lock.write(f'pid {os.getpid()} since {time.strftime("%Y-%m-%d %H:%M")}\n'); self._lock.flush()
        self._dotgit()
        self.base = self.git('rev-list', '--max-parents=0', 'HEAD').split()[0]
        self.task = self.base
        self.mk = open(os.path.join(self.build, 'Makefile'), encoding='utf-8', errors='replace').read()

    def git(self, *args, check=True):
        return sh(['git', '--git-dir', self.gitdir, '--work-tree', self.src, *args], self.src, check=check)

    def _dotgit(self):
        """the .git file of the tree (whatever the agent did to it)"""
        dot = os.path.join(self.src, '.git')
        if os.path.isdir(dot) and not os.path.islink(dot): shutil.rmtree(dot, ignore_errors=True)      # a repository the agent created itself
        want = f'gitdir: {self.taskgit}\n'
        if not os.path.isfile(dot) or open(dot, errors='replace').read() != want:
            if os.path.lexists(dot): os.remove(dot)
            open(dot, 'w').write(want)

    def _taskgit(self, msg):
        """the agent's repository for this task: the task commit's tree as a commit WITHOUT a parent, no reflog, no other refs"""
        tree = self.git('rev-parse', self.task + '^{tree}').split()[0]
        orphan = self.git('-c', 'user.name=bench', '-c', 'user.email=bench@localhost', 'commit-tree', tree, '-m', msg).split()[0]
        shutil.rmtree(self.taskgit, ignore_errors=True)
        os.makedirs(os.path.join(self.taskgit, 'objects', 'info')); os.makedirs(os.path.join(self.taskgit, 'refs', 'heads'))
        w = lambda rel, s: open(os.path.join(self.taskgit, rel), 'w').write(s)
        w('HEAD', 'ref: refs/heads/master\n'); w('refs/heads/master', orphan + '\n')
        w('config', '[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n\tbare = false\n\tlogallrefupdates = false\n')
        w('objects/info/alternates', os.path.join(self.gitdir, 'objects') + '\n')
        shutil.copy2(os.path.join(self.gitdir, 'index'), os.path.join(self.taskgit, 'index'))     # same tree: git status is instant
        self._dotgit()

    def reset(self):
        os.makedirs(self.src, exist_ok=True)
        for f in ('index.lock', 'HEAD.lock'):                             # left by a git process that was killed
            if os.path.exists(os.path.join(self.gitdir, f)): os.remove(os.path.join(self.gitdir, f))
        self._dotgit()
        self.git('reset', '-q', '--hard', self.base)                      # also restores every tracked file the agent deleted
        self.git('clean', '-qfdx')
        sf = os.path.join(self.build, '.bench_stop')
        if os.path.exists(sf): os.remove(sf)

    def _check_build(self):
        """before a task: the Makefile must not look out of date.  It depends on config.status and tools/makedep; when a task leaves
        one of them newer (makedep is relinked as soon as a header it includes gets a new timestamp, e.g. restored by reset()),
        every later make first tries to regenerate all makefiles - which fails here (the test sources are gone), so every
        ./compile of every later task in this tree fails.  -> True if the timestamp had to be put right."""
        mk = os.path.join(self.build, 'Makefile')
        newest = max(os.path.getmtime(os.path.join(self.build, f)) for f in ('config.status', os.path.join('tools', 'makedep')))
        if newest < os.path.getmtime(mk): return False
        os.utime(mk, (newest + 1, newest + 1))
        print(f'note: {self.build}: Makefile looked out of date after the previous task; timestamp repaired', flush=True)
        return True

    def stop_compiling(self):
        """after the compile limit: every further ./compile answers that the task is over"""
        open(os.path.join(self.build, '.bench_stop'), 'w').write('compile limit reached\n')

    def objects_of(self, src_file, module):
        return [m.group(1) for m in re.finditer(r'^(dlls/' + re.escape(module) + r'/(?:[\w.-]+/)?[\w.-]+\.o): \S*' + re.escape(src_file) + r'$', self.mk, re.M)]

    def setup(self, rec):
        """-> info dict (stub_line, removed helpers, targets)"""
        self.reset()
        repaired = self._check_build()
        self.stop_file = os.path.join(self.build, '.bench_stop')          # created by the runner when the compile limit is hit: ./compile then refuses
        if os.path.exists(self.stop_file): os.remove(self.stop_file)
        f = rec['function']; rel = f['file']; path = os.path.join(self.src, rel)
        orig = open(path, encoding='utf-8', errors='surrogateescape').read()
        hidden, hinfo = hide(orig, rec)
        open(path, 'w', encoding='utf-8', errors='surrogateescape').write(hidden)
        targets = build_targets(rec).split()
        for t in [f'dlls/{f["module"]}/x86_64-windows/{f["module"]}.o'] + self.objects_of(rel, f['module']) + targets:
            p = os.path.join(self.build, t)
            if os.path.exists(p): os.remove(p)                      # the original binary must not be in the build copy either
        open(os.path.join(self.src, 'compile'), 'w').write(COMPILE_SH.format(build=self.build, jobs=self.jobs, targets=' '.join(targets), module=f['module']))
        os.chmod(os.path.join(self.src, 'compile'), 0o755)
        self.git('add', '-A'); self.git('-c', 'user.name=bench', '-c', 'user.email=bench@localhost', 'commit', '-qm', f'task {rec["id"]} {f["module"]}!{f["name"]}')
        self.task = self.git('rev-parse', 'HEAD').split()[0]              # the agent's work is everything that differs from this commit
        self._taskgit(f'task {rec["id"]} {f["module"]}!{f["name"]}')
        self.rel = rel
        return dict(stub_line=hinfo['stub_line'], removed=hinfo['removed'], targets=targets, build_repaired=repaired)

    def patch(self):
        """the agent's changes vs the task commit: tracked and new files, minus ./compile and scratch files"""
        self._dotgit()
        self.git('reset', '-q', self.task, check=False)                   # the agent may have committed: compare with the task commit, not HEAD
        self.git('add', '-A', '--', '.', ':(exclude)compile', ':(exclude).git')
        d = self.git('diff', '--cached', '--no-color', self.task, '--', '.', ':(exclude)compile', ':(exclude).git', ':(exclude)*.patch', ':(exclude)*.txt', ':(exclude)*.log', ':(exclude)*.orig', ':(exclude)*.rej', ':(exclude)*.bak', ':(exclude)*.tmp', check=False)
        self.git('reset', '-q', self.task, check=False)
        return d

    def target_changed(self, patch):
        return bool(re.search(r'^\+\+\+ b/' + re.escape(self.rel) + r'$', patch, re.M))

    def files_in(self, patch):
        return sorted(set(re.findall(r'^\+\+\+ b/(\S+)', patch, re.M)))

    @staticmethod
    def _spellings(p):
        home = os.path.expanduser('~').rstrip('/')
        out = [p]
        if p.startswith(home + '/'): out += ['~' + p[len(home):], '$HOME' + p[len(home):], '${HOME}' + p[len(home):]]
        return out

    def violations(self, commands):
        out = []
        for c in commands:
            c = as_text(c); c2 = c
            for p, tag in ((self.src, '<TREE>'), (self.build, '<BUILD>')):   # the tree's own path is fine, however it is spelled
                for alt in self._spellings(p): c2 = c2.replace(alt, tag)
            for name, rx in RULES_RE:
                if re.search(rx, c2): out.append(dict(rule=name, command=c[:300])); break
        return out

COMPILE_SH = """#!/usr/bin/env bash
# ./compile - rebuild the {module} module with your current changes and show the compiler diagnostics.
# (This is the only build step you need; the rest of the project is already built.)
[ -e {build}/.bench_stop ] && {{ echo "compile limit reached: the task has ended and your current code is being submitted as it is."; exit 2; }}
out=$(cd {build} && make -j{jobs} {targets} 2>&1); rc=$?
if [ $rc -eq 0 ]; then
    warn=$(echo "$out" | grep -E ':[0-9]+:[0-9]+: warning:' | head -40)
    echo "compiled OK: {targets}"; [ -n "$warn" ] && echo "warnings:" && echo "$warn"
else
    echo "$out" | grep -E ':[0-9]+(:[0-9]+)?: (fatal )?(error|warning|note):|undefined reference|error:|^make' | head -80
    echo "compile FAILED (make exit status $rc)"
fi
exit $rc
"""

# ---------------------------------------------------------------- models
def litellm_name(m):
    """the litellm model string of a models.toml entry: explicit `litellm`, else derived from provider / base_url"""
    if m.get('litellm'): return m['litellm']
    if m['provider'] == 'anthropic': return 'anthropic/' + m['model']
    if 'deepseek' in m.get('base_url', ''): return 'deepseek/' + m['model']
    if 'api.openai.com' in m.get('base_url', ''): return 'openai/' + m['model']
    return 'openai/' + m['model']                                   # any other OpenAI-compatible endpoint: needs base_url too

def is_local(m):
    """a model served on this machine (vLLM on the job's node): no vendor-specific handling, everything in `extra` goes into the body"""
    return any(h in m.get('base_url', '') for h in ('127.0.0.1', 'localhost'))

def local_base_url(m):
    """base_url with the job's own port (WB_LOCAL_PORT, set by vulcan/agents.sbatch)"""
    u = m['base_url']; port = os.environ.get('WB_LOCAL_PORT')
    return re.sub(r':\d+/', f':{port}/', u) if port else u

def tool_mode(cfg, m=None):
    """native = the API's tool calls (the vendor APIs); text = the action is parsed from the reply text (mini-swe-agent's
    text-based model class, OpenHands' prompt-based function calling).
    Local models run in text mode unless told otherwise: server-side tool-call parsing of the cluster's vLLM proved
    unreliable for Qwen3.8 (wrong parser) and GLM.  SWE_LOCAL_TOOL_MODE=native, or tool_mode = "native" in the model's
    entry, switches a local model to native calls: gpt-oss needs that - it answers with harmony tool calls whatever the
    prompt asks for, which the server rejects when no tools are declared (see install_tool_name_fix for the other half).
    For API models SWE_TOOL_MODE / [swe].tool_mode apply."""
    if m is not None and is_local(m): return os.environ.get('SWE_LOCAL_TOOL_MODE') or m.get('tool_mode') or 'text'
    return os.environ.get('SWE_TOOL_MODE') or cfg.get('tool_mode', 'native')

# ---- tool names that a local server returns damaged
_argfixes = {}                                                         # thread id -> argument strings repaired since tool_arg_fixes_take()
_fix_lock = threading.Lock(); _fixes = {}                              # thread id -> names repaired since tool_fixes_take()
TOOL_NAME_FIXES = [0]                                                  # all of them, for the end-of-run line

def fixed_tool_name(name, declared):
    """vLLM's harmony output parsing (gpt-oss) loses the <|constrain|> token between the tool name and the content type:
    the call  to=functions.bash<|constrain|>json  comes back as the tool "bashjson" ("terminaljson", "finishjson" ...),
    which no agent knows.  -> the declared tool that was meant, or the name unchanged if that is not this case."""
    if not isinstance(name, str) or name in declared: return name
    n = name.strip()
    if n.startswith('functions.'): n = n[len('functions.'):]
    n = re.split(r'[\s<]', n, maxsplit=1)[0]
    if n in declared: return n
    for suffix in ('json', 'commentary'):                              # "bashjson", "bashcommentary"
        if n.lower().endswith(suffix) and n[:-len(suffix)] in declared: return n[:-len(suffix)]
    return name

def fixed_tool_args(args, props):
    """gpt-oss was trained on a shell tool whose arguments are {"cmd": ["bash", "-lc", "<script>"]}.  Asked for
    {"command": "<script>"} it sometimes (mostly on long multi-line commands) starts in our form and ends in its own:
    {"command":"...PATCH"]}  - invalid JSON, which it then repeats unchanged until the agent gives up - or uses "cmd"
    throughout.  Both are put back into the declared form; the command text itself is never changed.
    props = the parameter names of the declared tool.  -> the arguments string (unchanged if this is not one of the cases)."""
    if not isinstance(args, str) or 'command' not in props or 'cmd' in props: return args
    try: j = json.loads(args)
    except ValueError:
        t = args.rstrip()
        if not t.endswith('"]}'): return args
        t = t[:-3] + '"}'
        try: j = json.loads(t)
        except ValueError: return args
        return t if isinstance(j, dict) and isinstance(j.get('command'), str) else args
    if isinstance(j, dict) and 'command' not in j and 'cmd' in j:
        c = j['cmd']
        if isinstance(c, list) and c and all(isinstance(x, str) for x in c):
            if len(c) == 3 and c[0] in ('bash', 'sh', '/bin/bash', '/bin/sh') and c[1] in ('-lc', '-c'): c = c[2]
            elif len(c) == 1: c = c[0]
            else: c = shlex.join(c)
        if isinstance(c, str):
            return json.dumps({'command': c, **{k: v for k, v in j.items() if k != 'cmd' and k in props}})
    return args

def install_tool_name_fix():
    """wrap litellm.completion: in the reply of a LOCAL server (127.0.0.1 / localhost) a tool-call name that is not one of
    the declared tools but is one with "json" glued to it gets its real name back.  Nothing else of the reply is touched
    and API models are never affected.  Call it before the agent library is imported, and again after (OpenHands binds
    the function at import time)."""
    import litellm
    if not getattr(litellm.completion, '_bench_fix', False):
        orig = litellm.completion
        def completion(*args, **kw):
            r = orig(*args, **kw)
            try:
                base = str(kw.get('api_base') or kw.get('base_url') or '')
                declared = {t['function']['name']: set(((t['function'].get('parameters') or {}).get('properties') or {}))
                            for t in (kw.get('tools') or []) if isinstance(t, dict) and isinstance(t.get('function'), dict)}
                if declared and ('127.0.0.1' in base or 'localhost' in base):
                    for ch in getattr(r, 'choices', None) or []:
                        for tc in getattr(getattr(ch, 'message', None), 'tool_calls', None) or []:
                            new = fixed_tool_name(tc.function.name, declared)
                            if new != tc.function.name:
                                tc.function.name = new
                                with _fix_lock: _fixes[threading.get_ident()] = _fixes.get(threading.get_ident(), 0) + 1; TOOL_NAME_FIXES[0] += 1
                            if tc.function.name in declared:
                                new = fixed_tool_args(tc.function.arguments, declared[tc.function.name])
                                if new != tc.function.arguments:
                                    tc.function.arguments = new
                                    with _fix_lock: _argfixes[threading.get_ident()] = _argfixes.get(threading.get_ident(), 0) + 1
            except Exception: pass
            return r
        completion._bench_fix = True; litellm.completion = completion
    import sys
    mod = sys.modules.get('openhands.sdk.llm.llm')
    if mod is not None and hasattr(mod, 'litellm_completion') and not getattr(mod.litellm_completion, '_bench_fix', False):
        mod.litellm_completion = litellm.completion

def tool_fixes_take():
    """number of tool names repaired in this thread since the last call (0 for API models)"""
    with _fix_lock: return _fixes.pop(threading.get_ident(), 0)

def tool_arg_fixes_take():
    """number of tool-call argument strings repaired in this thread since the last call"""
    with _fix_lock: return _argfixes.pop(threading.get_ident(), 0)

def stale(result, mode):
    """a stored result produced in the other tool mode: it is run again (the old file is kept as <id>.attemptN.json)"""
    return bool(result.get('tool_mode')) and result['tool_mode'] != mode and result.get('exit_status') != 'DatasetMismatch'

def litellm_kwargs(m):
    """per-call parameters: the model's `extra` (thinking off, reasoning_effort) and max_tokens; temperature only if the model takes it"""
    kw = {}
    if m.get('max_tokens'): kw[m.get('max_tokens_field', 'max_tokens')] = m['max_tokens']
    extra = dict(m.get('extra') or {})
    if is_local(m):
        if extra: kw['extra_body'] = extra
        if m.get('send_temperature', True) and 'temperature' in m: kw['temperature'] = m['temperature']
        kw['api_base'] = local_base_url(m); kw['api_key'] = m.get('api_key') or 'none'
        return kw
    if 'reasoning_effort' in extra: kw['reasoning_effort'] = extra.pop('reasoning_effort')
    if 'thinking' in extra:
        if m['provider'] == 'anthropic': kw['thinking'] = extra.pop('thinking')
        else: kw.setdefault('extra_body', {})['thinking'] = extra.pop('thinking')     # DeepSeek: a body field litellm does not know
    if extra: kw.setdefault('extra_body', {}).update(extra)
    if m.get('send_temperature', True) and 'temperature' in m: kw['temperature'] = m['temperature']
    if m.get('base_url') and 'api.openai.com' not in m['base_url'] and m['provider'] != 'anthropic' and not m.get('litellm', '').startswith('deepseek/') and 'deepseek' not in m.get('base_url', ''):
        kw['api_base'] = m['base_url']
    return kw

def key_env(m, secrets):
    """export the key the way litellm wants it (ANTHROPIC_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY)"""
    key = m.get('api_key') or secrets.get(m['api_key_env']) or os.environ.get(m['api_key_env'], '')
    name = litellm_name(m).split('/')[0].upper() + '_API_KEY'
    if key: os.environ[name] = key; os.environ[m['api_key_env']] = key
    return key

# ---------------------------------------------------------------- API runs: one retry per task, no network for the agent
CONTEXT_RE = re.compile(r'context.?window|context.?length|maximum context|too many tokens|prompt is too long|input length', re.I)

def gen_failed(r):
    """--gen-attempts: did this agent run fail for a reason outside the model's work (network, API error, runner crash)?
    True  = the run was cut short by an exception / a conversation error -> the task may be run once more.
    False = the agent ended by itself or by one of the bench's limits (Submitted, LimitsExceeded, CompileLimit, TimeExceeded,
            Stuck, format errors), or the conversation outgrew the model's context window: that is the result of the task."""
    if r.get('exit_status') == 'DatasetMismatch': return False
    err = r.get('error') or ''; detail = r.get('error_detail') or ''             # error_detail: what ended an OpenHands conversation in state "error"
    if CONTEXT_RE.search(err + ' ' + detail) or 'ContextWindow' in (r.get('exit_status') or ''): return False
    return bool(err) or r.get('exit_status') in ('ModelError', 'RunnerError')

def run_capped(work, i, gen_attempts, out_dir, stub):
    """run task i at most gen_attempts times: again only if gen_failed(); write_result() keeps the earlier run as
    <id>.attemptK.json.  The final result gets generation_failed (true = every attempt failed).  stub(i, error) -> a
    minimal result for a task whose runner crashed before anything was stored, so that the task counts as done."""
    r = None
    for k in range(1, gen_attempts + 1):
        try: r = work(i)
        except BaseException as e: r = stub(i, f'{type(e).__name__}: {e}'[:300])
        if not gen_failed(r): break
        if k < gen_attempts: time.sleep(10)
    f = os.path.join(out_dir, i + '.json')
    if r.get('exit_status') == 'RunnerError':                         # nothing was stored for the last attempt
        write_result(out_dir, i, r, dict(id=i, error=r.get('error')), '')
    if os.path.exists(f):
        s = json.load(open(f)); s['generation_failed'] = gen_failed(s); s['gen_attempts_made'] = k
        r['generation_failed'] = s['generation_failed']; r['gen_attempts_made'] = k
        json.dump(s, open(f + '.tmp', 'w'), indent=1, ensure_ascii=False); os.replace(f + '.tmp', f)
    return r

PROXY_VARS = ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY')
def offline_env():
    """the job's proxy is for the model calls of this process only: the agent's shell commands get it blanked (as in the
    local-model runs, where the compute node has no route out at all)"""
    return {v: '' for v in PROXY_VARS} if any(os.environ.get(v) for v in PROXY_VARS) else {}

# ---------------------------------------------------------------- results
def write_result(out_dir, i, out, traj, patch):
    """<id>.json (same fields as run_agent.py), <id>.traj.json, <id>.patch (only when there is a submission)"""
    f = os.path.join(out_dir, i + '.json')
    if os.path.exists(f):
        old = json.load(open(f)); out['attempts'] = old.get('attempts', 1) + 1
        os.replace(f, f[:-5] + f'.attempt{out["attempts"] - 1}.json')
    json.dump(out, open(f + '.tmp', 'w'), indent=1, ensure_ascii=False); os.replace(f + '.tmp', f)
    json.dump(traj, open(os.path.join(out_dir, i + '.traj.json'), 'w'), indent=1, ensure_ascii=False, default=str)
    pf = os.path.join(out_dir, i + '.patch')
    if patch: open(pf, 'w', encoding='utf-8', errors='surrogateescape').write(patch)
    elif os.path.exists(pf): os.remove(pf)

def status_line(name, k, n, r):
    tc = r['tool_counts']
    return (f'[{name}] {k}/{n} {r["id"]} {r["dll"]}!{r["function"]}: {"ok" if r["format_ok"] else "no-code"} exit={r["exit_status"]} '
            f'steps={r["steps"]} cmds={tc.get("commands", 0)} compiles={len(r["compiles"])}{"(ok)" if r["compiled_ok_last"] else ""} '
            f'files={len(r.get("files", []))} viol={len(r.get("violations", []))} tokens={r["usage"]["prompt_tokens"]}+{r["usage"]["completion_tokens"]} '
            f'${r.get("cost", 0):.3f} {r["seconds"]}s' + (f'  ERR {r["error"][:80]}' if r.get('error') else '')
            + (f'  [attempt {r["gen_attempts_made"]}{", GENERATION FAILED" if r.get("generation_failed") else ""}]' if r.get('gen_attempts_made', 1) > 1 or r.get('generation_failed') else ''))

COMPILE_CMD_RE = re.compile(r'(^|[\s;&|])\./compile\b|\bmake\b')

def as_text(x):
    """a tool argument that should be a string but may come back as anything from the model"""
    if isinstance(x, str): return x
    if x is None: return ''
    if isinstance(x, dict) and isinstance(x.get('command'), str): return x['command']   # {"command": {"command": "..."}}
    try: return json.dumps(x, ensure_ascii=False)
    except Exception: return str(x)

def compile_result(command, output, rc):
    """None if the command is not a compile; else True (ok) / False (failed).  ./compile prints 'compiled OK' / 'compile FAILED'
    (its exit status is lost behind a pipe such as `./compile | tail`); a bare make counts by its exit status."""
    command = as_text(command); o = as_text(output)
    if not COMPILE_CMD_RE.search(command): return None
    if './compile' in command:
        if 'compile limit reached' in o: return None                    # refused after the limit: not an attempt
        if 'compile FAILED' in o: return False
        if 'compiled OK' in o: return True
        return rc == 0 if rc is not None and rc >= 0 else False
    return rc == 0

def compiles_from(calls):
    """[(command, output, returncode)] -> the ./compile / make calls and whether they succeeded"""
    out = []
    for c, o, rc in calls:
        r = compile_result(c, o, rc)
        if r is not None: out.append(dict(ok=r, command=as_text(c)[:120]))
    return out
