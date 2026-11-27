#!/usr/bin/env python3
"""tree_access.py - did an agent reach outside the tree of its own task?

    python3 vulcan/tree_access.py [--root .] [--out results]

Every agent job runs several tasks at once, each in its own restricted tree, and all trees of a job sit side by side
(/t/wine-swe, /t/wine-swe-w1, ...).  A tree hides only the function of ITS task, so the original implementation of a
task's function is readable in the sibling trees.  The project directory with the dataset (which holds the original
code too) is mounted in the container as well.  Nothing blocks either; this script reports what the agents did, from
the commands in the trajectories:

  sibling        a command or file edit names a tree other than the task's own
  sibling_target ... and names the source file of the task's function there (the original implementation was in reach)
  sibling_write  a command that writes while naming another tree (the agent may have changed another task's tree)
  wide_search    a search or listing from / or /t (find /, ls -R /, grep -r ... /t): how siblings are usually found
  project        a command names the project directory, the scratch directory (where the clean Wine tree is) or a dataset:
                 the cluster's apptainer module mounts all of /project and /scratch into every container

Reads   wine_agent/runs/scenario<S>/<harness>/responses/<model>/<id>.json + .traj.json, eval/<model>/<id>.json
Writes  <out>/tree_access_tasks.csv     one line per task and setting with any of the above
        <out>/tree_access_settings.txt  one line per setting: counts, and how many of those tasks passed
"""
import os, re, sys, json, glob, csv, argparse

ROOT_RE = re.compile(r'(?<![\w.-])(?:/t/)?(wine-swe(?:-w\d+)?)(?![\w-])')            # a tree root, absolute or relative to /t
WRITE_RE = re.compile(r"sed\s+-i|>>?\s*[\w./$~-]|\btee\b|open\([^)]*['\"][wa]['\"]|\.write\(|python3?\s+-\s*<<|\bpatch\b|git\s+apply|\bcp\b|\bmv\b|\brm\b|cat\s*<<")
WIDE_RE = re.compile(r"(?:\bfind\s+/(?:t)?(?:\s|$)|\bls\s+(?:-\w+\s+)*/(?:t/?)?(?:\s|$|;|&|\|)|grep\s+-\w*[rR]\w*\b[^|;&]*\s/(?:t/?)?(?:\s|$)|\bdu\s+(?:-\w+\s+)*/(?:t/?)?(?:\s|$)|\btree\s+/(?:t/?)?(?:\s|$))")
PROJECT_RE = re.compile(r'/project/|/scratch/|winebench-w|wine_agent|wine_bench|winebench205|/dataset/')      # project directory, clean Wine tree, datasets

def jload(f):
    try: return json.load(open(f, encoding='utf-8', errors='replace'))
    except Exception: return None

def commands_mini(traj):
    own = (((traj.get('info') or {}).get('config') or {}).get('environment') or {}).get('cwd') or ''
    cmds = [str(a.get('command') or '') for m in traj.get('messages', []) if m.get('role') == 'assistant' for a in ((m.get('extra') or {}).get('actions') or [])]
    return os.path.basename(own.rstrip('/')), cmds

def commands_openhands(traj):
    own = ''; cmds = []
    for e in traj.get('events', []):
        act = e.get('action') if isinstance(e.get('action'), dict) else None
        if act:
            if isinstance(act.get('command'), str) and 'path' not in act: cmds.append(act['command'])
            elif act.get('path'): cmds.append(f"[edit:{act.get('command')}] {act['path']}")
        obs = e.get('observation') if isinstance(e.get('observation'), dict) else None
        if obs and not own:
            wd = ((obs.get('metadata') or {}).get('working_dir') or '') if isinstance(obs.get('metadata'), dict) else ''
            m = ROOT_RE.search(wd)
            if m: own = m.group(1)
    if not own:                                           # the workspace is named in what the agent is told at the start
        m = re.search(r'/t/(wine-swe(?:-w\d+)?)(?![\w-])', json.dumps([e for e in traj.get('events', []) if not isinstance(e.get('action'), dict)][:3]))
        if m: own = m.group(1)
    return own, cmds

def dataset_of(scen):                                 # the leakage settings (2.x-new, 2.x-old) have their own datasets
    return 'leak2024_' + scen.rsplit('-', 1)[1] if scen.endswith(('-new', '-old')) else 'winebench205_doc'

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--root', default=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))); ap.add_argument('--out', default='')
    a = ap.parse_args(); root = os.path.abspath(a.root); out = a.out or os.path.join(root, 'results'); rows = []; settings = []
    for d in sorted(glob.glob(os.path.join(root, 'wine_agent', 'runs', 'scenario*', '*', 'responses', '*'))):
        p = d.split(os.sep); scen, harness, model = p[-4][8:], p[-3], p[-1]
        s = dict(scenario=scen, harness=harness, model=model, tasks=0, passed=0, own_unknown=0, sibling=0, sibling_target=0, sibling_write=0, wide_search=0, project=0,
                 sibling_passed=0, sibling_target_passed=0, foreign_patch=0, foreign_patch_passed=0)
        for f in sorted(glob.glob(os.path.join(d, '[0-9][0-9][0-9][0-9].json'))):
            r = jload(f); traj = jload(f[:-5] + '.traj.json')
            if not r or not traj: continue
            e = jload(os.path.join(os.path.dirname(os.path.dirname(d)), 'eval', model, r['id'] + '.json')) or {}
            own, cmds = (commands_openhands if harness == 'openhands' else commands_mini)(traj)
            s['tasks'] += 1; ok = e.get('status') == 'pass'; s['passed'] += ok
            if not own:                                   # fall back: the root named most often
                c = {}
                for x in cmds:
                    for m in ROOT_RE.finditer(x): c[m.group(1)] = c.get(m.group(1), 0) + 1
                own = max(c, key=c.get) if c else ''; s['own_unknown'] += 1
            target = os.path.basename((r.get('hidden') or {}).get('file') or '') or os.path.basename(next(iter(r.get('files') or []), ''))
            rec = jload(next(iter(glob.glob(os.path.join(root, 'wine_agent', 'dataset', dataset_of(scen), r['id'] + '_*.json'))), '')) or {}
            target = os.path.basename((rec.get('function') or {}).get('file') or target)
            tfile = (rec.get('function') or {}).get('file') or ''; tdir = '/'.join(tfile.split('/')[:2])
            foreign = [x for x in (r.get('files') or []) if tdir and not x.startswith(tdir + '/')]      # files of the patch outside the task's module: written by somebody else?
            sib = sibt = sibw = wide = proj = 0; others = set()
            for x in cmds:
                roots = {m.group(1) for m in ROOT_RE.finditer(x)} - ({own} if own else set())
                if roots:
                    sib += 1; others |= roots
                    if target and target in x: sibt += 1
                    if WRITE_RE.search(x) and not x.startswith('[edit:view]'): sibw += 1
                if WIDE_RE.search(x): wide += 1
                if PROJECT_RE.search(x): proj += 1
            s['foreign_patch'] += bool(foreign); s['foreign_patch_passed'] += bool(foreign) and ok
            if sib or wide or proj or foreign:
                rows.append(dict(scenario=scen, harness=harness, model=model, id=r['id'], function=f"{r.get('dll')}!{r.get('function')}", own_tree=own, status=e.get('status', ''),
                                 sibling_commands=sib, sibling_target_commands=sibt, sibling_write_commands=sibw, wide_search_commands=wide, project_commands=proj,
                                 foreign_files=' '.join(foreign[:4]), other_trees=' '.join(sorted(others)), has_patch=int(bool(r.get('format_ok'))), steps=r.get('steps')))
            s['sibling'] += bool(sib); s['sibling_target'] += bool(sibt); s['sibling_write'] += bool(sibw); s['wide_search'] += bool(wide); s['project'] += bool(proj)
            s['sibling_passed'] += bool(sib) and ok; s['sibling_target_passed'] += bool(sibt) and ok
        if s['tasks']: settings.append(s)
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(out, 'tree_access_tasks.csv'), 'w', newline='', encoding='utf-8') as f:
        cols = ['scenario', 'harness', 'model', 'id', 'function', 'own_tree', 'status', 'has_patch', 'steps', 'sibling_commands', 'sibling_target_commands',
                'sibling_write_commands', 'wide_search_commands', 'project_commands', 'other_trees', 'foreign_files']
        w = csv.DictWriter(f, cols); w.writeheader(); w.writerows(rows)
    cols = ['scenario', 'harness', 'model', 'tasks', 'passed', 'sibling', 'sibling_target', 'sibling_write', 'wide_search', 'project', 'sibling_passed', 'sibling_target_passed', 'foreign_patch', 'foreign_patch_passed', 'own_unknown']
    wd = {c: max(len(c), *(len(str(s[c])) for s in settings)) for c in cols}
    with open(os.path.join(out, 'tree_access_settings.txt'), 'w', encoding='utf-8') as f:
        f.write('  '.join(c.ljust(wd[c]) for c in cols) + '\n')
        for s in settings: f.write('  '.join(str(s[c]).ljust(wd[c]) for c in cols) + '\n')
    print(open(os.path.join(out, 'tree_access_settings.txt')).read())
    print(f'{len(rows)} task lines -> {out}/tree_access_tasks.csv')

if __name__ == '__main__':
    main()
