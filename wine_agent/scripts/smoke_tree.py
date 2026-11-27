#!/usr/bin/env python3
"""smoke_tree.py - check every restricted tree pair without a model: set up one task, look at the tree the way an agent
would (git must show no history), run ./compile, take the patch, reset.

    python3 scripts/smoke_tree.py --src /t/wine-swe --build /t/wine-build-swe --workers 6 [--id 0001]
Exit status 0 only if every tree passes.  Used by vulcan/rebuild_trees.sbatch.
"""
import os, sys, argparse, subprocess
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bench.config import load_scenario
from bench.dataset import load_records
from bench import swe

def run(cmd, cwd):
    p = subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, errors='replace', timeout=900)
    return p.returncode, (p.stdout + p.stderr).strip()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True); ap.add_argument('--build', required=True)
    ap.add_argument('--workers', type=int, default=1); ap.add_argument('--id', default='0001'); ap.add_argument('--scenario', default='2.1')
    a = ap.parse_args()
    rec = load_records(load_scenario(a.scenario).dataset, ids=a.id)[0]
    rel = rec['function']['file']; bad = 0
    for i in range(a.workers):
        sfx = f'-w{i}' if i else ''; problems = []
        try:
            tree = swe.SweTree(a.src + sfx, a.build + sfx, 4, f'w{i}')
            tree.setup(rec)
            rc, out = run('git log --oneline --all | wc -l', tree.src)
            if out.split()[-1:] != ['1']: problems.append(f'git log --all shows {out!r} commits, wanted 1')
            rc, out = run(f'git show HEAD~1:{rel}', tree.src)
            if rc == 0: problems.append('git show HEAD~1:<file> works: the clean commit is reachable')
            rc, out = run('git reflog | wc -l', tree.src)
            if out.split()[-1:] != ['0']: problems.append(f'reflog has {out!r} lines')
            rc, out = run('git status --short', tree.src)
            if rc or out: problems.append(f'git status not clean after setup: rc={rc} {out[:200]!r}')
            rc, out = run('./compile', tree.src)
            print(f'  w{i} ./compile rc={rc}: {out[-300:]!r}', flush=True)
            if 'could not create Makefile' in out or 'config.status' in out or 'No rule to make target' in out: problems.append('the build tree is broken (Makefile regeneration)')
            if 'compiled OK' not in out and 'compile FAILED' not in out: problems.append('./compile printed neither result line')
            open(os.path.join(tree.src, rel), 'a').write('\n/* smoke test */\n')
            p = tree.patch()
            if not tree.target_changed(p): problems.append('patch() does not show the change to the target file')
            if 'TODO(bench)' in p.replace('/* smoke test */', '') and p.count('\n+') > 3: problems.append('patch() contains more than the smoke change')
            tree.reset()
            rc, out = run('git status --short 2>&1 | head -3', tree.src)
        except BaseException as e:
            problems.append(f'{type(e).__name__}: {e}'[:500])
        print(f'w{i}: ' + ('PASS' if not problems else 'FAIL - ' + '; '.join(problems)), flush=True); bad += bool(problems)
    sys.exit(1 if bad else 0)

if __name__ == '__main__':
    main()
