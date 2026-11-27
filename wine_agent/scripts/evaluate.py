#!/usr/bin/env python3
"""evaluate.py - does the programmer's code compile inside Wine, and does it pass Wine's own tests?  (Linux)

    python3 scripts/evaluate.py --src ~/wine --build ~/wine-build --scenario 1.1 --stage programmer --models M       # one-shot
    python3 scripts/evaluate.py --src ~/wine --build ~/wine-build --scenario 2.2 --stage mini_swe                    # agent, every model
    python3 scripts/evaluate.py --src ~/wine --build ~/wine-build --scenario 1.1 --baseline                  # clean-tree test results only
    python3 scripts/evaluate.py --src ~/wine --scenario 1.1 --stage programmer --models M --dry-run                  # splice only, no build (works on macOS)
    python3 scripts/evaluate.py --table                                                                      # one table over all evaluations

For every record that has a usable reply (responses/<model>/<id>.c):
  1. splice   the reply replaces the function in its source file (bench/csplice.py): helpers it defines replace
              same-named ones in the file or are added; macros / types it defines are added unless the file has them
  2. compile  make <the module's dll targets>  (plus the dlls of the test modules that compile the same file)
  3. test     for every test file that references the export: make <that test>.ok, compared with the same test on the
              untouched tree (the baseline, computed on demand and cached in runs/baseline/).  A failure that is new
              compared with the baseline fails the record; the test is re-run once to filter flaky failures.
  4. restore  the source file is written back with its old timestamp and the clean build outputs saved before step 2
              are put back, so no rebuild is needed (checked with make -q; falls back to a rebuild, or always
              rebuild with --rebuild-restore).  Interrupted runs are repaired at the next start from the backups.
Results: runs/<scenario>/<stage>[/from_M]/eval/<model>/<id>.json and summary.json.  Record status:
  no_code | splice_fail | compile_fail | test_fail | crash | timeout | pass | no_tests
Needs a configured and fully built Wine tree (scripts/setup_eval_ubuntu.sh).  On a headless machine run it under
xvfb-run -a, because many tests need a display.

Agent stages (splice_base = "hidden"): the reply is spliced into the file as the agent saw it (bench/hide.py: stub +
exclusive helpers removed); reply_format = "patch" takes <id>.patch, a diff against that hidden tree, every touched file
backed up and restored.

Parallel: --workers N evaluates N records at once, each in its own copy of the tree (scripts/make_eval_trees.sh N):
  worker 0 = --src/--build/--prefix, worker i = <src>-w<i>, <build>-w<i>, <prefix>-w<i>; each worker gets its own
  Xvfb display (tests that move the mouse or take the focus would disturb each other on a shared one).
"""
import os, sys, re, json, glob, time, argparse, subprocess, signal, statistics, tempfile, shutil, threading, queue, atexit, fcntl
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import load_scenario, add_scenario_args, ROOT
from bench.dataset import load_records
from bench import csplice
try: from bench.hide import hide; from bench.agent import stub_record       # agent stages (wine_agent); absent in a plain wine_bench
except ImportError: hide = stub_record = None

# ---------------------------------------------------------------- processes
# Memory watch.  Generated code can make a compiler or a Wine test eat memory without end; on a cluster node that gets the
# whole evaluation killed by the kernel (the job's cgroup limit) and nothing of the tasks in flight is kept.  So every
# command started by sh() is watched: when the processes of its session together hold more than MEM['limit_mb'] of
# resident memory they are killed and the command's output ends with MEM_MARK; a test killed that way counts as a crash,
# a compile as a failed compile.  Two more rules for what a session sum cannot see:
#   - a single process outside any watched session (a Wine service or wineserver of a prefix) above the limit is killed;
#   - when the job's cgroup is nearly full (anonymous + shared memory > 90 % of its limit) the largest watched session goes.
# mem_watch(0) switches it off; nothing happens where /proc is not Linux's.
MEM = dict(limit_mb=0, sessions={}, killed={}, lock=threading.Lock(), thread=None)
MEM_MARK = '[killed: memory limit'

def _proc_table():
    """{pid: (session id, resident MB, command name)} of this user's processes"""
    t = {}; page = os.sysconf('SC_PAGE_SIZE'); uid = os.getuid()
    for d in os.listdir('/proc'):
        if not d.isdigit(): continue
        try:
            if os.stat('/proc/' + d).st_uid != uid: continue
            s = open(f'/proc/{d}/stat').read(); k = s.rindex(')')
            t[int(d)] = (int(s[k + 2:].split()[3]), (int(open(f'/proc/{d}/statm').read().split()[1]) * page) >> 20, s[s.index('(') + 1:k])
        except (OSError, ValueError, IndexError): continue
    return t

def _cgroup_dir():
    """(directory, limit MB) of the nearest cgroup (v2) with a memory limit above this process, or None"""
    try:
        rel = [l.split('::', 1)[1].strip() for l in open('/proc/self/cgroup') if l.startswith('0::')][0]
        d = os.path.normpath('/sys/fs/cgroup/' + rel)
        while d.startswith('/sys/fs/cgroup'):
            f = os.path.join(d, 'memory.max')
            if os.path.exists(f):
                v = open(f).read().strip()
                if v != 'max': return d, int(v) >> 20
            if d == '/sys/fs/cgroup': break
            d = os.path.dirname(d)
    except (OSError, ValueError, IndexError): pass
    return None

def _cgroup_used(d):
    """anonymous + shared memory of the cgroup in MB (the page cache is left out: the kernel gives it back)"""
    u = 0
    for l in open(os.path.join(d, 'memory.stat')):
        k, v = l.split()
        if k in ('anon', 'shmem'): u += int(v)
    return u >> 20

def _mem_loop(cg):
    me = os.getpid(); warned = 0
    def kill(t, sid, used, why):
        for pid, (s, _, _) in t.items():
            if s == sid:
                try: os.kill(pid, signal.SIGKILL)
                except OSError: pass
        with MEM['lock']: what = MEM['sessions'].get(sid, '?'); MEM['killed'][sid] = used
        print(f'    [mem] killed ({why}): {used} MB held by: {what}', flush=True)
    while True:
        time.sleep(2); lim = MEM['limit_mb']
        if not lim: continue
        try:
            t = _proc_table(); by = {}
            for pid, (sid, rss, _) in t.items(): by[sid] = by.get(sid, 0) + rss
            with MEM['lock']: watched = [s for s in MEM['sessions'] if s not in MEM['killed']]
            for sid in watched:
                if by.get(sid, 0) > lim: kill(t, sid, by[sid], f'limit {lim} MB'); watched = [s for s in watched if s != sid]
            for pid, (sid, rss, comm) in t.items():
                if rss > lim and pid != me and sid not in MEM['sessions']:
                    try: os.kill(pid, signal.SIGKILL)
                    except OSError: pass
                    print(f'    [mem] killed process {pid} ({comm}): {rss} MB, limit {lim} MB', flush=True)
            if cg:
                used = _cgroup_used(cg[0])
                if used > 0.9 * cg[1]:
                    big = max(watched, key=lambda s: by.get(s, 0), default=None)
                    if big is not None and by.get(big, 0) > 256: kill(t, big, by[big], f'job memory {used} of {cg[1]} MB')
                    elif time.time() - warned > 60:
                        warned = time.time(); top = sorted(t.items(), key=lambda x: -x[1][1])[:5]
                        print(f'    [mem] job memory {used} of {cg[1]} MB and no command to blame; largest processes: '
                              + ', '.join(f'{c}({p}) {r} MB' for p, (_, r, c) in top), flush=True)
        except Exception as e:
            if time.time() - warned > 300: warned = time.time(); print(f'    [mem] watch error: {type(e).__name__}: {e}', flush=True)

def mem_watch(limit_mb):
    """start (once) the watch described above; WB_MEM_LIMIT_MB overrides the limit, 0 = off"""
    limit_mb = int(os.environ.get('WB_MEM_LIMIT_MB', limit_mb)); MEM['limit_mb'] = limit_mb
    if not limit_mb or MEM['thread'] or not os.path.exists('/proc/self/statm'): return
    cg = _cgroup_dir()
    MEM['thread'] = threading.Thread(target=_mem_loop, args=(cg,), daemon=True); MEM['thread'].start()
    print(f'memory watch: {limit_mb} MB per command (compile or test run)' + (f'; job limit {cg[1]} MB' if cg else '; no cgroup limit visible'), flush=True)

def sh(cmd, cwd, timeout, env=None):
    """run a command; returns (rc, output, seconds, timed_out).  On timeout the whole process group is killed.
    Output goes through a temporary file, not a pipe: Wine's service processes outlive the test and would keep a pipe open.
    A command killed by the memory watch returns like a crashed one (rc -9) with MEM_MARK at the end of its output."""
    t0 = time.time()
    with tempfile.TemporaryFile(mode='w+', encoding='utf-8', errors='replace') as f:
        p = subprocess.Popen(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT, env=env, start_new_session=True)
        with MEM['lock']: MEM['sessions'][p.pid] = ' '.join(str(c) for c in cmd)[-90:]
        try: rc = p.wait(timeout=timeout); to = False
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL); p.wait(); rc = -1; to = True
        with MEM['lock']: MEM['sessions'].pop(p.pid, None); used = MEM['killed'].pop(p.pid, None)
        f.seek(0); out = f.read()
    if used: out += f'\n{MEM_MARK} {MEM["limit_mb"]} MB, the command held {used} MB]'
    return rc, out + ('\n[killed after timeout]' if to else ''), round(time.time() - t0, 1), to

ERR_RE = re.compile(r'^(?:\S+:\d+(?::\d+)?: (?:fatal )?error: .*|.*undefined reference to .*|.*error: .*unresolved.*|winebuild: .*error.*|.*: error: .*)$', re.M)
FAIL_RE = re.compile(r'^(?:[0-9a-f]+:)?(?:\S*/)?([\w.-]+\.c):(\d+):\S* Test (failed|succeeded inside todo block)', re.M)   # file:line:[elapsed] Test failed: ...
SUM_RE = re.compile(r'^(?:[0-9a-f]+:)?(\w+):\S* (\d+) tests? executed \((\d+) marked as todo,(?: (\d+) as flaky,)? (\d+) failures?\), (\d+) skipped\.', re.M)   # pid:name:[elapsed] N tests executed (...)

class Fatal(Exception): pass

WINE_VERSION = '11.19'                                              # the dataset's Wine; git restores only go back to this
XVFB_ARGS = ['-screen', '0', '1280x1024x24', '-nolisten', 'tcp']      # the same screen as xvfb-run's default

MIN_FREE_GB = 2
def wait_for_space(paths, what=''):
    """a full disk makes every compile fail and every restore look broken: wait (and say so) instead of going on"""
    warned = False
    while True:
        low = [(p, shutil.disk_usage(p).free / 2**30) for p in paths if os.path.exists(p) and shutil.disk_usage(p).free < MIN_FREE_GB * 2**30]
        if not low: return
        if not warned: print(f'!! low disk space {what}: ' + ', '.join(f'{p}: {g:.1f} GB free' for p, g in low) + f' - waiting until >= {MIN_FREE_GB} GB is free (free some space, this run continues by itself)', flush=True)
        warned = True; time.sleep(60)

def start_xvfb():
    """a private Xvfb on a free display number -> ':N' (killed at exit)"""
    r, w = os.pipe()
    p = subprocess.Popen(['Xvfb', '-displayfd', str(w)] + XVFB_ARGS, pass_fds=(w,), stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    os.close(w)
    with os.fdopen(r) as f: num = f.readline().strip()
    if not num: sys.exit('Xvfb did not start (sudo apt install xvfb)')
    atexit.register(lambda: (p.terminate(), p.wait()))
    return ':' + num

class Wine:
    """a configured Wine build directory"""
    def __init__(self, src, build, jobs, compile_timeout, test_timeout, prefix, display=None, name='w0'):
        self.src, self.build, self.jobs, self.name = os.path.abspath(src), os.path.abspath(build), jobs, name
        self.compile_timeout, self.test_timeout = compile_timeout, test_timeout
        mk = os.path.join(self.build, 'Makefile')
        if not os.path.exists(mk): sys.exit(f'{self.build}: no Makefile (run configure first, see scripts/setup_eval_ubuntu.sh)')
        self.mk = open(mk, encoding='utf-8', errors='replace').read()
        self.all = []
        for m in re.finditer(r'^all:[ \t]*(.*?)(?<!\\)$', self.mk, re.S | re.M): self.all += m.group(1).replace('\\\n', ' ').split()
        self.env = dict(os.environ)
        if prefix: self.env['WINEPREFIX'] = os.path.expanduser(prefix)
        if display: self.env['DISPLAY'] = display
        self._built_tests = set()
        self.snapdir = os.path.join(self.build, '.eval_snapshot')
        self._lock = open(os.path.join(self.build, '.eval.lock'), 'a+')     # one evaluate.py per tree: two would corrupt each other's files
        try: fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._lock.seek(0); who = self._lock.read().strip()
            sys.exit(f'{self.build} is in use by another evaluate.py ({who or "unknown pid"}): wait for it, or use other trees')
        self._lock.seek(0); self._lock.truncate(); self._lock.write(f'pid {os.getpid()} since {time.strftime("%Y-%m-%d %H:%M")}\n'); self._lock.flush()

    def git_dirty(self):
        """tracked files modified in the source tree (a git checkout), or [] (not a git tree / clean)"""
        if not os.path.isdir(os.path.join(self.src, '.git')): return []
        p = subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=self.src, capture_output=True, text=True, errors='replace')
        return [l[3:].strip() for l in p.stdout.splitlines() if l[:2].strip() in ('M', 'MM', 'D')]

    def git_restore(self, files):
        """put tracked files back to the committed version; returns the modules that must be rebuilt"""
        subprocess.run(['git', 'checkout', '--', *files], cwd=self.src, capture_output=True)
        for x in files: os.utime(os.path.join(self.src, x), None)      # make must rebuild from the restored text
        return sorted({m for x in files for m in self.modules_compiling(x)})

    def ensure_clean(self, where=''):
        """a dirty git tree (another process, an interrupted run of another package) is restored and rebuilt before use"""
        dirty = self.git_dirty()
        if not dirty: return True
        ver = open(os.path.join(self.src, 'VERSION')).read().strip() if os.path.exists(os.path.join(self.src, 'VERSION')) else '?'
        head = subprocess.run(['git', 'log', '-1', '--format=%h %s'], cwd=self.src, capture_output=True, text=True).stdout.strip()
        if WINE_VERSION not in ver or WINE_VERSION not in head:          # never "restore" to anything but the benchmark's Wine
            sys.exit(f'{self.src}: modified files {dirty[:5]} but the checkout is "{ver}" / HEAD "{head}", not Wine {WINE_VERSION}: not touching it')
        print(f'[{self.name}] {where}{self.src} has modified files: {dirty[:8]}{" ..." if len(dirty) > 8 else ""} - restoring them from git ({head}) and rebuilding', flush=True)
        mods = self.git_restore(dirty)
        ok, o, _ = self.make([t for m in mods for t in self.module_targets(m)])
        if not ok: print(f'[{self.name}] rebuild after git restore failed:\n{o[-1500:]}', flush=True)
        return ok

    def ensure_prefix(self):
        """create the WINEPREFIX if it does not exist yet (without the Mono / Gecko dialog, which would hang under Xvfb)"""
        pfx = self.env.get('WINEPREFIX')
        if not pfx or os.path.exists(os.path.join(pfx, 'system.reg')): return
        if not os.path.exists(os.path.join(self.build, 'wine')): sys.exit(f'{self.build}/wine missing: Wine is not fully built')
        print(f'[{self.name}] creating Wine prefix {pfx} ...', flush=True)
        env = dict(self.env, WINEDLLOVERRIDES='mscoree,mshtml=', WINEDEBUG='-all')
        sh([os.path.join(self.build, 'wine'), 'wineboot', '-u'], self.build, 600, env)
        rc, *_ = sh([os.path.join(self.build, 'server', 'wineserver'), '-w'], self.build, 120, env)
        if rc: sh([os.path.join(self.build, 'server', 'wineserver'), '-k'], self.build, 60, env)

    def objects_of(self, src_file, module):
        """object files of dlls/<module> compiled from this source file"""
        return [m.group(1) for m in re.finditer(r'^(dlls/' + re.escape(module) + r'/(?:[\w.-]+/)?[\w.-]+\.o): \S*' + re.escape(src_file) + r'$', self.mk, re.M)]

    def outputs(self, src_file, modules):
        """every build output that changes when src_file changes and these modules are rebuilt"""
        return sorted({t for m in modules for t in self.objects_of(src_file, m) + self.module_targets(m)})

    def snapshot(self, files):
        """move-safe copies of the clean outputs (timestamps kept)"""
        shutil.rmtree(self.snapdir, ignore_errors=True); os.makedirs(self.snapdir)
        for i, t in enumerate(files):
            p = os.path.join(self.build, t)
            if os.path.exists(p): shutil.copy2(p, os.path.join(self.snapdir, str(i)))

    def restore_snapshot(self, files):
        """put the clean outputs back (new inodes: a lingering Wine process may still map the old dll);
        an output that did not exist before is removed, so it can never be mistaken for a clean one"""
        for i, t in enumerate(files):
            p, s = os.path.join(self.build, t), os.path.join(self.snapdir, str(i))
            if os.path.exists(s): os.replace(s, p)
            elif os.path.exists(p): os.remove(p)
        shutil.rmtree(self.snapdir, ignore_errors=True)

    def up_to_date(self, targets):
        rc, *_ = sh(['make', '-q'] + targets, self.build, 300, self.env)
        return rc == 0

    def module_targets(self, module):
        """the dll / .so files of dlls/<module> (not its tests)"""
        return [t for t in self.all if t.startswith(f'dlls/{module}/') and '/tests/' not in t]

    def modules_compiling(self, src_file):
        """modules whose objects are built from this source file (PARENTSRC: several)"""
        return sorted({m.group(1) for m in re.finditer(r'^dlls/([^/\s]+)/(?:[\w.-]+/)?[\w.-]+\.o: \S*' + re.escape(src_file) + r'$', self.mk, re.M)})

    def test_exe(self, module):
        return [t for t in self.all if t.startswith(f'dlls/{module}/tests/')]

    def ok_target(self, module, name):
        m = re.search(r'^(dlls/' + re.escape(module) + r'/tests/(?:[\w.-]+/)?' + re.escape(name) + r'\.ok):', self.mk, re.M)
        return m.group(1) if m else None

    def make(self, targets, timeout=None):
        """(ok, output, seconds)"""
        if not targets: return True, '', 0.0
        rc, out, secs, to = sh(['make', '-j', str(self.jobs)] + targets, self.build, timeout or self.compile_timeout, self.env)
        return rc == 0 and not to, out, secs

    def build_module(self, module):
        if not self.module_targets(module):
            return dict(ok=False, seconds=0, errors=[f'dlls/{module} is not built in this tree (missing dependency at configure time?)'], output_tail='')
        ok, out, secs = self.make(self.module_targets(module))
        errors = [re.sub(r'^\S*?(?=dlls/|include/|libs/|programs/)', '', l.strip()) for l in ERR_RE.findall(out)]   # drop the ../src/ or absolute prefix
        if MEM_MARK in out: errors.insert(0, 'the build was killed: it used more memory than the limit of the evaluation')
        return dict(ok=ok, seconds=secs, errors=errors[:30], output_tail=out[-3000:] if not ok else '')

    def run_test(self, test_file, rerun=False):
        """test_file = dlls/<module>/tests/<name>.c  ->  dict(status, executed, failed[], todo_ok[], seconds, output_tail)"""
        module, name = test_file.split('/')[1], os.path.basename(test_file)[:-2]
        if module not in self._built_tests:
            ok, out, _ = self.make(self.test_exe(module))
            if not ok: return dict(status='test_build_failed', output_tail=out[-2000:], failed=[], todo_ok=[], executed=0, seconds=0)
            self._built_tests.add(module)
        target = self.ok_target(module, name)
        if not target: return dict(status='no_such_test', failed=[], todo_ok=[], executed=0, seconds=0, output_tail='')
        ok_file = os.path.join(self.build, target)
        if os.path.exists(ok_file): os.remove(ok_file)
        # RUNTESTFLAGS without -q: quiet mode sets WINETEST_DEBUG=0, which also silences the summary line
        rc, out, secs, to = sh(['make', '-s', target, 'RUNTESTFLAGS=-P wine'], self.build, self.test_timeout, self.env)
        if os.path.exists(ok_file): os.remove(ok_file)
        mem = MEM_MARK in out                                        # the memory watch killed the test: a crash
        if to or mem: sh([os.path.join(self.build, 'server', 'wineserver'), '-k'], self.build, 60, self.env)   # kill what the test left behind
        failed = sorted({f'{f}:{l}' for f, l, k in FAIL_RE.findall(out) if k == 'failed'})
        todo_ok = sorted({f'{f}:{l}' for f, l, k in FAIL_RE.findall(out) if k != 'failed'})
        sums = SUM_RE.findall(out)                                   # child processes print their own summary: take this test's
        s = ([m for m in sums if m[0] == name] or sums or [None])[-1]
        status = 'timeout' if to else 'ok' if s and not mem else 'crash'
        return dict(status=status, executed=int(s[1]) if s else 0, failures=int(s[4]) if s else None, **({'mem_killed': True} if mem else {}),
                    failed=failed, todo_ok=todo_ok, seconds=secs, output_tail=out[-2500:] if status != 'ok' or failed else '')

# ---------------------------------------------------------------- baseline
_baseline_locks, _locks_lock = {}, threading.Lock()

def baseline(wine, test_file, bdir):
    f = os.path.join(bdir, test_file.replace('/', '__')[:-2] + '.json')
    with _locks_lock: lock = _baseline_locks.setdefault(f, threading.Lock())
    with lock:                                                        # two workers must not compute the same one
        if os.path.exists(f): return json.load(open(f))
        print(f'    [{wine.name}] baseline {test_file}: running (timeout {wine.test_timeout}s) ...', flush=True)
        r = wine.run_test(test_file); r.update(test=test_file, date=time.strftime('%Y-%m-%d %H:%M'))
        os.makedirs(bdir, exist_ok=True); json.dump(r, open(f + '.tmp', 'w'), indent=1); os.replace(f + '.tmp', f)
        print(f'    [{wine.name}] baseline {test_file}: {r["status"]}, {r["executed"]} tests, {len(r["failed"])} failures, {r["seconds"]}s', flush=True)
        return r

BAD_BASELINE = ('timeout', 'crash', 'test_build_failed', 'no_such_test')

def judge(new, base, strict_todo):
    """verdict of one test run against its baseline"""
    if base['status'] in BAD_BASELINE: return 'skipped', []
    if new['status'] == 'timeout': return 'timeout', []
    if new['status'] == 'crash': return 'crash', sorted(set(new['failed']) - set(base['failed']))
    new_fail = sorted(set(new['failed']) - set(base['failed']))
    if strict_todo: new_fail += sorted(set(new['todo_ok']) - set(base['todo_ok']))
    return ('fail' if new_fail else 'pass'), new_fail

# ---------------------------------------------------------------- one record
def _read(path): return open(path, encoding='utf-8', errors='surrogateescape').read() if os.path.exists(path) else None
def _write(path, text):
    if text is None:
        if os.path.exists(path): os.remove(path)
    else:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, 'w', encoding='utf-8', errors='surrogateescape').write(text)

def prepare_code(src, rec, llm_code, a, out):
    """programmer / agent stages: the reply is C source spliced into the function's file -> {rel: new text} or None"""
    f = rec['function']; rel = f['file']; orig = _read(os.path.join(src, rel))
    try:
        if a.splice_base == 'hidden':                                # agent stages: into the file as the agent saw it
            base, hinfo = hide(orig, rec); new, info = csplice.splice(base, stub_record(rec, base), llm_code); info['hidden'] = hinfo
        else: new, info = csplice.splice(orig, rec, llm_code)
    except csplice.SpliceError as e:
        out.update(status='splice_fail', splice=dict(error=str(e))); return None
    out['splice'] = info
    tc = csplice.target_code(llm_code, f['name'])
    out['identical'] = csplice.normalize(tc) == csplice.normalize(f['code']); out['similarity'] = csplice.similarity(tc, f['code'])
    if a.dry_run: _write(os.path.join(a.spliced_dir, rec['id'] + '.spliced.c'), new)
    return {rel: new}

def prepare_patch(src, rec, patch, a, out):
    """agent stages with reply_format = "patch": a diff against the HIDDEN tree (bench/hide.py) -> {rel: new text} per touched file"""
    f = rec['function']; rel = f['file']; orig = _read(os.path.join(src, rel))
    files = sorted(set(re.findall(r'^(?:\+\+\+ b|--- a)/(\S+)', patch, re.M)))
    out['patch'] = dict(files=files, lines=patch.count('\n'))
    if rel not in files: out.update(status='splice_fail', splice=dict(error='the patch does not touch the function\'s file')); return None
    try: hidden, hinfo = hide(orig, rec)
    except csplice.SpliceError as e:
        out.update(status='splice_fail', splice=dict(error=str(e))); return None
    out['patch']['hidden'] = hinfo
    with tempfile.TemporaryDirectory() as tmp:                      # apply in a scratch copy of the touched files
        for x in files:
            t = hidden if x == rel else _read(os.path.join(src, x))
            if t is not None: _write(os.path.join(tmp, x), t)
        _write(os.path.join(tmp, 'x.patch'), patch)
        rc, o, _, _ = sh(['git', 'apply', '--whitespace=nowarn', 'x.patch'], tmp, 120)
        if rc != 0: out.update(status='splice_fail', splice=dict(error='git apply failed: ' + o[-400:])); return None
        new = {x: _read(os.path.join(tmp, x)) for x in files}
    tc = csplice.target_code(new[rel] or '', f['name'])
    if tc is None: out.update(status='splice_fail', splice=dict(error=f'{f["name"]} is not defined after the patch')); return None
    out['identical'] = csplice.normalize(tc) == csplice.normalize(f['code']); out['similarity'] = csplice.similarity(tc, f['code'])
    if a.dry_run: _write(os.path.join(a.spliced_dir, rec['id'] + '.spliced.c'), new[rel])
    return new

def evaluate_record(wine, rec, reply, kind, bdir, backup_dir, a):
    f = rec['function']; rel = f['file']; src = wine.src if wine else a.src
    out = dict(id=rec['id'], function=f['name'], export=f['export_name'], module=f['module'], file=rel)
    new = prepare_patch(src, rec, reply, a, out) if kind == 'patch' else prepare_code(src, rec, reply, a, out)
    if new is None: return out
    if a.dry_run: out['status'] = 'spliced'; return out

    tests = rec.get('native_tests', {}).get('files', []) if not a.no_tests else []
    test_mods = {t.split('/')[1] for t in tests}
    modules = [f['module']]
    for x in new:                                                       # other modules that compile a touched file and are tested
        modules += [m for m in wine.modules_compiling(x) if m not in modules and (m in test_mods or x != rel)]
    out['modules_built'] = modules
    bases = {t: baseline(wine, t, bdir) for t in tests}            # on the clean tree, before touching anything

    originals = {x: _read(os.path.join(src, x)) for x in new}
    backup = os.path.join(backup_dir, rec['id'] + '.backup.json')
    json.dump(dict(files=originals, src=wine.src, build=wine.build), open(backup, 'w'))
    stats = {x: os.stat(os.path.join(src, x)) for x in new if os.path.exists(os.path.join(src, x))}
    outs = [] if a.rebuild_restore else sorted({t for x in new for t in wine.outputs(x, modules)})
    wine.snapshot(outs)
    for x, t in new.items(): _write(os.path.join(src, x), t)
    try:
        results = []
        for m in modules:
            c = wine.build_module(m); c['module'] = m; results.append(c)
            if not c['ok']: break
        out['compile'] = results if len(results) > 1 else results[0]
        if not all(c['ok'] for c in results): out['status'] = 'compile_fail'; return out
        out['tests'] = []
        for t in tests:
            if bases[t]['status'] in BAD_BASELINE:                         # the clean tree cannot run it either: nothing to compare
                out['tests'].append(dict(file=t, verdict='skipped', status='baseline_' + bases[t]['status'], executed=0,
                                         failures=None, new_failures=[], todo_fixed=[], baseline_failures=None, seconds=0,
                                         rerun=None, output_tail='')); continue
            r = wine.run_test(t); verdict, new_fail = judge(r, bases[t], a.strict_todo)
            if verdict in ('fail', 'crash') and not a.no_rerun:         # once more, to drop flaky failures
                r2 = wine.run_test(t); v2, nf2 = judge(r2, bases[t], a.strict_todo)
                if v2 == 'pass' or (v2 == 'fail' and verdict == 'fail'):
                    new_fail = sorted(set(new_fail) & set(nf2)); verdict = 'fail' if new_fail else 'pass'
                    r['rerun'] = dict(status=r2['status'], failed=r2['failed'])
            out['tests'].append(dict(file=t, verdict=verdict, status=r['status'], executed=r['executed'],
                                     failures=r.get('failures'), new_failures=new_fail,
                                     todo_fixed=sorted(set(r['todo_ok']) - set(bases[t]['todo_ok'])),
                                     baseline_failures=len(bases[t]['failed']), seconds=r['seconds'],
                                     rerun=r.get('rerun'), output_tail=r['output_tail']))
        verdicts = [t['verdict'] for t in out['tests']]
        out['status'] = ('no_tests' if not [v for v in verdicts if v != 'skipped'] else
                         'crash' if 'crash' in verdicts else 'timeout' if 'timeout' in verdicts else
                         'test_fail' if 'fail' in verdicts else 'pass')
        return out
    finally:
        for x, t in originals.items(): _write(os.path.join(src, x), t)
        targets = [t for m in modules for t in wine.module_targets(m)]
        if outs:                                                      # old timestamps + saved clean outputs: no rebuild
            for x, st in stats.items(): os.utime(os.path.join(src, x), ns=(st.st_atime_ns, st.st_mtime_ns))
            wine.restore_snapshot(outs)
            if not wine.up_to_date(targets):
                for x in stats: os.utime(os.path.join(src, x), None)
                out['restore'] = 'rebuilt'                            # make -q disagrees: rebuild for real
                ok, o, _ = wine.make(targets)
            else: ok, o = True, ''; out['restore'] = 'snapshot'
        else:
            ok, o, _ = wine.make(targets); out['restore'] = 'rebuilt'
        if not ok:                                                    # something else is wrong: disk full? another process? git knows the rest
            wait_for_space([wine.build, tempfile.gettempdir()], f'while restoring {rel}')
            ok, o, _ = wine.make(targets)
        if not ok:
            if not wine.git_dirty() or not wine.ensure_clean('after a failed restore of ' + rel + ': '):
                raise Fatal(f'{wine.src}/{rel} restored but the clean rebuild failed (make said: {o[-2000:] or "nothing"}; '
                            f'free: build {shutil.disk_usage(wine.build).free / 2**30:.1f} GB, tmp {shutil.disk_usage(tempfile.gettempdir()).free / 2**30:.1f} GB)')
            ok, o, _ = wine.make(targets)
            if not ok: raise Fatal(f'{wine.src}/{rel} restored but the clean rebuild failed:\n{o[-2000:]}')
        os.remove(backup)

# ---------------------------------------------------------------- summary / table
def summarize(edir, n_records):
    rs = [json.load(open(f)) for f in glob.glob(os.path.join(edir, '[0-9][0-9][0-9][0-9].json'))]
    st = [r['status'] for r in rs]
    tested = [r for r in rs if r['status'] in ('pass', 'test_fail', 'crash', 'timeout')]
    s = dict(model=os.path.basename(edir), records=n_records, evaluated=len(rs),
             with_code=sum(1 for x in st if x != 'no_code'), spliced=sum(1 for x in st if x not in ('no_code', 'splice_fail')),
             compiled=sum(1 for x in st if x in ('pass', 'test_fail', 'crash', 'timeout', 'no_tests')),
             tested=len(tested), passed=st.count('pass'), test_fail=st.count('test_fail'), crash=st.count('crash'),
             timeout=st.count('timeout'), compile_fail=st.count('compile_fail'), splice_fail=st.count('splice_fail'),
             no_tests=st.count('no_tests'), identical=sum(1 for r in rs if r.get('identical')),
             mean_similarity=round(statistics.mean([r['similarity'] for r in rs if 'similarity' in r]), 4) if any('similarity' in r for r in rs) else None,
             todo_fixed=sum(len(t['todo_fixed']) for r in tested for t in r.get('tests', [])))
    json.dump(s, open(os.path.join(edir, 'summary.json'), 'w'), indent=1)
    return s

def table(runs, csv):
    rows = []
    for f in sorted(glob.glob(os.path.join(runs, 'scenario*', '**', 'eval', '*', 'summary.json'), recursive=True)):
        rel = os.path.relpath(f, runs).split(os.sep)                   # scenarioX/stage[/from_M]/eval/model/summary.json
        s = json.load(open(f)); n = s['records'] or 1
        rows.append({'scenario': rel[0][8:], 'stage': rel[1], 'from': rel[2][5:] if rel[2].startswith('from_') else '-',
                     'model': s['model'], 'records': s['records'], 'code': s['with_code'], 'compiled': s['compiled'],
                     'compile%': round(100 * s['compiled'] / n, 1), 'tested': s['tested'], 'passed': s['passed'],
                     'pass%': round(100 * s['passed'] / n, 1), 'test_fail': s['test_fail'], 'crash': s['crash'],
                     'timeout': s['timeout'], 'no_tests': s['no_tests'], 'identical': s['identical'], 'similarity': s['mean_similarity']})
    if not rows: sys.exit(f'no eval/*/summary.json under {runs}')
    cols = list(rows[0])
    if csv: print(','.join(cols)); [print(','.join(str(r[c]) for c in cols)) for r in rows]; return
    w = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print('  '.join(c.ljust(w[c]) for c in cols))
    for r in rows: print('  '.join(str(r[c]).ljust(w[c]) for c in cols))

# ---------------------------------------------------------------- main
def make_trees(a):
    """one Wine per worker: worker 0 = --src/--build/--prefix, worker i = <src>-w<i>, <build>-w<i>, <prefix>-w<i>"""
    mem_watch(getattr(a, 'mem_limit_mb', 4096))
    jobs = a.jobs or max(2, (os.cpu_count() or 2) // a.workers)
    trees = []
    for i in range(a.workers):
        sfx = f'-w{i}' if i else ''
        src, build = a.src.rstrip('/') + sfx, os.path.abspath(os.path.expanduser(a.build)).rstrip('/') + sfx
        if not os.path.isdir(src) or not os.path.exists(os.path.join(build, 'Makefile')):
            sys.exit(f'worker {i}: {src} / {build} missing - run:  bash scripts/make_eval_trees.sh {a.workers}')
        display = start_xvfb() if a.workers > 1 or a.own_xvfb else None
        w = Wine(src, build, jobs, a.compile_timeout, a.timeout, a.prefix.rstrip('/') + sfx, display, f'w{i}')
        trees.append(w)
    if a.workers > 1: print(f'{a.workers} workers, make -j{jobs} each: ' + ', '.join(f'{w.name}={w.build} {w.env["DISPLAY"]}' for w in trees), flush=True)
    return trees

def repair_trees(a, trees):
    """restore source files left modified by an interrupted run (in whichever tree they were modified)"""
    by_src = {w.src: w for w in trees}
    for b in glob.glob(os.path.join(a.runs, '**', '*.backup.json'), recursive=True):
        d = json.load(open(b)); src = d.get('src', a.src)
        files = d['files'] if 'files' in d else {d['file']: d['content']}
        print(f'repairing {src}: {list(files)} from {b}', flush=True)
        for x, t in files.items(): _write(os.path.join(src, x), t)       # new mtime: forces a recompile
        w = by_src.get(src) or Wine(src, d.get('build', a.build), a.jobs or os.cpu_count() or 2, a.compile_timeout, a.timeout, None)
        targets = [t for x in files for m in w.modules_compiling(x) for t in w.module_targets(m)]
        ok, o, _ = w.make(targets)                                       # clean dlls again
        if not ok and w.git_dirty() and w.ensure_clean('while repairing: '): ok, o, _ = w.make(targets)
        if not ok: sys.exit(f'FATAL: rebuild after repairing {list(files)} failed:\n{o[-2000:]}')
        os.remove(b)

def run_parallel(trees, items, fn):
    """fn(wine, item) for every item, each call on a free tree; yields (item, result) as they finish"""
    free = queue.Queue(); [free.put(w) for w in trees]
    stop = threading.Event()
    def work(item):
        if stop.is_set(): return None
        w = free.get()
        try: return fn(w, item)
        except BaseException: stop.set(); raise
        finally: free.put(w)
    with ThreadPoolExecutor(max_workers=len(trees)) as ex:
        futs = {ex.submit(work, it): it for it in items}
        try:
            for fu in as_completed(futs):
                r = fu.result()
                if r is not None: yield futs[fu], r
        except BaseException:
            stop.set(); [fu.cancel() for fu in futs]; raise

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_scenario_args(ap)
    ap.add_argument('--src', help='Wine source tree (the files are modified in place and restored)')
    ap.add_argument('--build', help='configured Wine build directory (out of tree is fine)')
    ap.add_argument('--models', default='', help='comma-separated model names (default: every responses/<model>/ of the stage)')
    ap.add_argument('--workers', type=int, default=1, help='records evaluated at once, one tree each (scripts/make_eval_trees.sh)')
    ap.add_argument('--jobs', type=int, default=0, help='make -j per worker (default: CPUs / workers, at least 2)')
    ap.add_argument('--timeout', type=int, default=300, help='seconds per test run (default 300; the clean-tree runs of the benchmark tests take < 1 min)')
    ap.add_argument('--compile-timeout', type=int, default=1800)
    ap.add_argument('--mem-limit-mb', type=int, default=4096, help='a compile or test run whose processes hold more resident memory than this is killed (crash / failed compile); 0 = no limit')
    ap.add_argument('--prefix', default='~/.wine-bench', help='WINEPREFIX for the test runs')
    ap.add_argument('--own-xvfb', action='store_true', help='start a private Xvfb even with one worker (default with --workers > 1)')
    ap.add_argument('--rebuild-restore', action='store_true', help='restore the tree by rebuilding instead of putting back saved outputs')
    ap.add_argument('--redo', action='store_true', help='re-evaluate records that already have a result')
    ap.add_argument('--dry-run', action='store_true', help='splice only; write eval/<model>/<id>.spliced.c, no build')
    ap.add_argument('--no-tests', action='store_true', help='compile only')
    ap.add_argument('--no-rerun', action='store_true', help='do not re-run a failing test to filter flaky failures')
    ap.add_argument('--strict-todo', action='store_true', help='count "succeeded inside todo block" as a failure')
    ap.add_argument('--baseline', action='store_true', help='only run the clean-tree baselines of the scenario\'s records')
    ap.add_argument('--runs', default=os.path.join(ROOT, 'runs'))
    ap.add_argument('--table', action='store_true'); ap.add_argument('--csv', action='store_true')
    a = ap.parse_args()
    if a.table: return table(a.runs, a.csv)
    if not a.scenario or not a.src: ap.error('--scenario and --src are required')
    if not a.dry_run and not a.build: ap.error('--build is required (or --dry-run)')
    scn = load_scenario(a.scenario); st = scn.stage(a.stage); a.splice_base = st.get('splice_base', 'original')
    if a.splice_base == 'hidden' and hide is None: sys.exit('this stage splices into the hidden file: scripts/bench/hide.py and agent.py are needed (copy them from wine_agent)')
    kind = 'patch' if st.get('reply_format') == 'patch' else 'code'
    if st.get('input_stage') and not a.from_model: ap.error(f'stage {a.stage} needs --from-model')
    records = load_records(scn.dataset, a.ids, a.limit)
    stage_dir = scn.out(a.stage, a.from_model or None)
    bdir = os.path.join(a.runs, 'baseline')
    a.src = os.path.abspath(os.path.expanduser(a.src))
    if a.dry_run: a.workers = 1
    trees = [None] if a.dry_run else make_trees(a)
    if not a.dry_run:
        for w in trees:                                              # git first: it also covers what the backups know, and more
            if not w.ensure_clean(): sys.exit(f'FATAL: {w.src} could not be brought back to a clean state')
        repair_trees(a, trees)
        for w in trees: w.ensure_prefix()
    if a.baseline:
        tests = sorted({t for rec in records for t in rec.get('native_tests', {}).get('files', [])})
        for _ in run_parallel(trees, tests, lambda w, t: baseline(w, t, bdir)): pass
        return

    models = a.models.split(',') if a.models else sorted(os.path.basename(d) for d in glob.glob(os.path.join(stage_dir, 'responses', '*')) if os.path.isdir(d))
    for model in models:
        rdir = os.path.join(stage_dir, 'responses', model); edir = os.path.join(stage_dir, 'eval', model)
        os.makedirs(edir, exist_ok=True); a.spliced_dir = edir
        todo = [r for r in records if a.redo or not os.path.exists(os.path.join(edir, r['id'] + '.json'))]
        print(f'[{model}] {len(todo)} records to evaluate ({len(records) - len(todo)} already done)', flush=True)

        def one(wine, rec):
            wait_for_space([wine.build, tempfile.gettempdir(), edir], f'before {rec["id"]}')
            cf = os.path.join(rdir, rec['id'] + ('.patch' if kind == 'patch' else '.c')); t0 = time.time()
            if not os.path.exists(cf): out = dict(id=rec['id'], function=rec['function']['name'], status='no_code')
            else:
                reply = open(cf, encoding='utf-8', errors='replace').read()
                out = evaluate_record(wine, rec, reply, kind, bdir, edir, a)
            out.update(model=model, scenario=scn.name, stage=a.stage, from_model=a.from_model or None, seconds=round(time.time() - t0, 1))
            tmp = os.path.join(edir, rec['id'] + '.json.tmp')                      # atomic: an interrupted write must not look like a result
            json.dump(out, open(tmp, 'w'), indent=1, ensure_ascii=False); os.replace(tmp, os.path.join(edir, rec['id'] + '.json'))
            return out

        try:
            for k, (rec, out) in enumerate(run_parallel(trees, todo, one), 1):
                extra = ''
                if out['status'] == 'compile_fail':
                    c = out['compile'] if isinstance(out['compile'], dict) else out['compile'][-1]
                    extra = ' | ' + (c['errors'][0][:90] if c['errors'] else 'see output_tail')
                elif out['status'] in ('test_fail', 'crash'): extra = ' | new failures: ' + ', '.join(f for t in out['tests'] for f in t['new_failures'])[:120]
                elif out['status'] == 'splice_fail': extra = ' | ' + out['splice']['error'][:90]
                print(f'[{model}] {k}/{len(todo)} {rec["id"]} {rec["function"]["module"]}!{rec["function"]["name"]}: {out["status"]}{extra}  ({out["seconds"]}s)', flush=True)
        except Fatal as e:
            sys.exit(f'FATAL: {e}')
        print(f'[{model}] summary: {summarize(edir, len(records))}', flush=True)

if __name__ == '__main__':
    main()
