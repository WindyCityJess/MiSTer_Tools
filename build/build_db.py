#!/usr/bin/env python3
"""Build the Downloader database (db.json.zip) for MiSTer_Tools.

Every tool lists its SD-card files in tools/<name>/files.txt (paths relative to /media/fat, which
is the repo's own layout: Scripts/...). Each file gets the tags [essential, <tool>] so it installs
even under a positive [mister] filter, and a user can drop one tool with `!<tool>` in the filter.

usage: build_db.py --sha <commit> [--out dist/db.json.zip] [--check]
       --check only validates (every file under Scripts/ belongs to exactly one tool, paths are valid)
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_ID = 'windycityjess/mister_tools'
REPO = 'WindyCityJess/MiSTer_Tools'
PAYLOAD_ROOTS = ['Scripts']  # top-level SD-card folders this repo ships


def norm(term):
    return term.lower().replace('-', '').replace('_', '')


def load_tools():
    tools = {}
    tdir = os.path.join(ROOT, 'tools')
    for name in sorted(os.listdir(tdir)):
        manifest = os.path.join(tdir, name, 'files.txt')
        if not os.path.isfile(manifest):
            continue
        with open(manifest, encoding='utf-8') as f:
            paths = [l.strip() for l in f if l.strip() and not l.lstrip().startswith('#')]
        tools[name] = paths
    return tools


def payload_files():
    out = []
    for top in PAYLOAD_ROOTS:
        for d, _, fs in os.walk(os.path.join(ROOT, top)):
            for f in fs:
                if f.endswith('.pyc') or '__pycache__' in d:
                    continue
                out.append(os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, '/'))
    return sorted(out)


def validate(tools):
    errors, owner = [], {}
    for name, paths in tools.items():
        for p in paths:
            if p.startswith(('/', '.', '\\')) or '..' in p.split('/') or p.split('/')[0] not in PAYLOAD_ROOTS:
                errors.append('%s: invalid path %s' % (name, p))
            elif not os.path.isfile(os.path.join(ROOT, p)):
                errors.append('%s: missing file %s' % (name, p))
            if p in owner:
                errors.append('%s listed by both %s and %s' % (p, owner[p], name))
            owner[p] = name
    for p in payload_files():
        if p not in owner:
            errors.append('%s is not listed in any tools/<name>/files.txt' % p)
    return errors


def build(tools, sha):
    tag_names = ['essential'] + [norm(n) for n in tools]
    tag_dictionary = {t: i for i, t in enumerate(tag_names)}
    essential = tag_dictionary['essential']
    files, folders = {}, {}
    for name, paths in tools.items():
        tag = tag_dictionary[norm(name)]
        for p in paths:
            with open(os.path.join(ROOT, p), 'rb') as f:
                data = f.read()
            files[p] = {'hash': hashlib.md5(data).hexdigest(), 'size': len(data),
                        'url': 'https://raw.githubusercontent.com/%s/%s/%s' % (REPO, sha, p),
                        'tags': [essential, tag]}
            parts = p.split('/')[:-1]
            for i in range(1, len(parts) + 1):
                folder = '/'.join(parts[:i])
                ftags = folders.setdefault(folder, {'tags': [essential]})['tags']
                if i > 1 and tag not in ftags and folder.split('/')[-1].lower() == name.lower():
                    ftags.append(tag)  # the tool's own folder, e.g. Scripts/.config/<tool>
    ts = int(subprocess.run(['git', '-C', ROOT, 'log', '-1', '--format=%ct', sha], capture_output=True,
                            text=True, check=True).stdout.strip())
    return {'db_id': DB_ID, 'timestamp': ts, 'files': files, 'folders': folders,
            'tag_dictionary': tag_dictionary}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sha')
    ap.add_argument('--out', default=os.path.join(ROOT, 'dist', 'db.json.zip'))
    ap.add_argument('--check', action='store_true')
    args = ap.parse_args()
    tools = load_tools()
    errors = validate(tools)
    for e in errors:
        print('ERROR: ' + e)
    if errors:
        return 1
    print('%d tools, %d files OK' % (len(tools), sum(len(v) for v in tools.values())))
    if args.check:
        return 0
    if not args.sha:
        ap.error('--sha is required to build')
    db = build(tools, args.sha)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with zipfile.ZipFile(args.out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('db.json', json.dumps(db, indent=2, sort_keys=True))
    print('wrote %s (%d files)' % (args.out, len(db['files'])))
    return 0


if __name__ == '__main__':
    sys.exit(main())
