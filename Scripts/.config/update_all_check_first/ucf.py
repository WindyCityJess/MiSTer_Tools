#!/usr/bin/env python3
# update_all_check_first helper (ucf.py)
#
# Runs before Update All. Downloads every database listed in downloader.ini (+ drop-in
# downloader_*.ini files), works out what Downloader WOULD install, and:
#   - updates to already-installed files ............ install automatically
#   - new non-core content (wallpapers, MGLs, manuals,
#     BIOS, docs...) .................................. install automatically
#   - new cores (console/computer/arcade/other/utility)
#     and new scripts ................................. need approval
# Every new core/script is INSTALLED, BLOCKED (added to the downloader.ini filter so it never
# shows again) or DEFERRED (filtered for this run only: the term is removed again after Update
# All finishes, so the item is offered again next time).
#
# Safety: a filter term is only offered for blocking when NO installed file carries that tag,
# because Downloader deletes installed files that a filter excludes.
#
# Exit codes: 0 = continue with Update All, 1 = user cancelled, 2 = error (do not update).
# Usage: ucf.py                    interactive (dialog menus)
#        ucf.py --report           print the analysis only, change nothing
#        ucf.py --release-deferred remove this run's deferred terms (the launcher calls it after Update All)

import concurrent.futures
import configparser
import datetime
import hashlib
import io
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

BASE = '/media/fat'
MAIN_INI = BASE + '/downloader.ini'
STORE = BASE + '/Scripts/.config/downloader/downloader.json'
CONF_DIR = BASE + '/Scripts/.config/update_all_check_first'
STATE = CONF_DIR + '/blocked.json'
HISTORY = CONF_DIR + '/history.log'
DEFERRED = CONF_DIR + '/deferred.json'  # terms filtered for the current run only
CACHE = '/tmp/ucf_cache'
CERTS = [os.environ.get('SSL_CERT_FILE', ''), BASE + '/Scripts/.config/downloader/cacert.pem',
         '/etc/ssl/certs/cacert.pem']
# Update All rewrites the filter line of these databases on every run, so a block there would not stick.
UA_OWNED_FILTER_DBS = {'coin-opcollection/distribution-misterfpga', 'ranny-snice/ranny-snice-wallpapers'}
TERM_RE = re.compile(r'^[a-z0-9]+[-_a-z0-9.]*$')
BACKTITLE = 'Update All - Check First'
CATEGORY_ORDER = ['Console', 'Computer', 'Arcade', 'Other', 'Utility', 'Scripts']
CORE_FOLDERS = {'_console': 'Console', '_computer': 'Computer', '_arcade': 'Arcade',
                '_other': 'Other', '_utility': 'Utility'}


def norm(term):
    return str(term).lower().replace('-', '').replace('_', '')


# ---------------------------------------------------------------- ini handling

def read_ini(path):
    cp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'), interpolation=None, strict=False)
    with open(path, encoding='utf-8', errors='replace') as f:
        cp.read_string(f.read())
    return cp


def ini_value(section, key):
    if key not in section:
        return None
    return section[key].strip().strip('"\' ')


def load_databases():
    """Return (global_filter or None, [db dicts]) using Downloader's discovery rules."""
    main = read_ini(MAIN_INI)
    global_filter = None
    for s in main.sections():
        if s.lower() == 'mister':
            global_filter = ini_value(main[s], 'filter')
    dbs, seen = [], set()

    def add(cp, path):
        for s in cp.sections():
            sid = s.lower()
            if sid == 'mister' or sid in seen:
                continue
            url = ini_value(cp[s], 'db_url')
            if not url:
                continue
            seen.add(sid)
            dbs.append({'id': sid, 'section': s, 'url': url, 'ini': path,
                        'filter': ini_value(cp[s], 'filter')})

    add(main, MAIN_INI)
    drop_dir = os.path.join(BASE, 'downloader')
    drop_ins = []
    if os.path.isdir(drop_dir):
        drop_ins += sorted(os.path.join(drop_dir, f) for f in os.listdir(drop_dir)
                           if f.endswith('.ini') and not f.startswith('.'))
    drop_ins += sorted(os.path.join(BASE, f) for f in os.listdir(BASE)
                       if f.startswith('downloader_') and f.endswith('.ini'))
    for p in drop_ins:
        try:
            add(read_ini(p), p)
        except Exception as e:  # a broken drop-in is skipped by Downloader too
            print('WARNING: could not read %s: %s' % (p, e))
    return global_filter, dbs


def add_filter_terms(path, section_name, terms):
    """Append !terms to `filter =` in [section_name] of the ini at path, keeping every other line as-is."""
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.read().split('\n')
    target = section_name.lower()
    in_sec, sec_start, filt_line = False, None, None
    for i, line in enumerate(lines):
        m = re.match(r'^\s*\[(.+?)\]\s*$', line)
        if m:
            in_sec = m.group(1).strip().lower() == target
            if in_sec:
                sec_start = i
            continue
        if in_sec and re.match(r'^\s*filter\s*=', line, re.I):
            filt_line = i
    addition = ' '.join('!' + t for t in terms)
    if filt_line is not None:
        line = lines[filt_line]
        existing = set(line.split('=', 1)[1].lower().split())
        new = [('!' + t) for t in terms if ('!' + t) not in existing]
        if not new:
            return
        lines[filt_line] = line.rstrip() + ' ' + ' '.join(new)
    elif sec_start is not None:
        lines.insert(sec_start + 1, 'filter = ' + addition)
    else:
        lines = ['[%s]' % section_name, 'filter = ' + addition, ''] + lines
    write_with_backup(path, '\n'.join(lines))


def remove_filter_terms(path, section_name, terms):
    with open(path, encoding='utf-8', errors='replace') as f:
        lines = f.read().split('\n')
    target, in_sec, changed = section_name.lower(), False, False
    drop = {'!' + norm(t) for t in terms}
    for i, line in enumerate(lines):
        m = re.match(r'^\s*\[(.+?)\]\s*$', line)
        if m:
            in_sec = m.group(1).strip().lower() == target
            continue
        if in_sec and re.match(r'^\s*filter\s*=', line, re.I):
            key, val = line.split('=', 1)
            parts = val.split()
            kept = [p for p in parts if ('!' + norm(p[1:]) if p.startswith('!') else p) not in drop]
            if len(kept) != len(parts):
                lines[i] = key.rstrip() + ' = ' + ' '.join(kept)
                changed = True
    if changed:
        write_with_backup(path, '\n'.join(lines))


def write_with_backup(path, contents):
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup = '%s.bak_ucf_%s' % (path, stamp)
    if not os.path.exists(backup):  # several writes in one second: keep the oldest (pre-change) copy
        shutil.copy2(path, backup)
    tmp = path + '.ucf_tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(contents)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    # keep the 10 newest ucf backups per file
    folder, name = os.path.split(path)
    olds = sorted(f for f in os.listdir(folder) if f.startswith(name + '.bak_ucf_'))
    for f in olds[:-10]:
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass


# ---------------------------------------------------------------- database fetching

def ssl_context():
    for c in CERTS:
        if c and os.path.isfile(c):
            return ssl.create_default_context(cafile=c)
    return ssl.create_default_context()


def fetch_json(url, ctx):
    os.makedirs(CACHE, exist_ok=True)
    cache_file = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())
    req = urllib.request.Request(url, headers={'User-Agent': 'update_all_check_first'})
    data = urllib.request.urlopen(req, context=ctx, timeout=60).read()
    with open(cache_file, 'wb') as f:
        f.write(data)
    if data[:2] == b'PK':
        z = zipfile.ZipFile(io.BytesIO(data))
        data = z.read(z.namelist()[0])
    return json.loads(data.decode('utf-8'))


def fetch_db(db, ctx):
    d = fetch_json(db['url'], ctx)
    files = dict(d.get('files', {}))
    archives = dict(d.get('archives', {}))
    archives.update(d.get('zips', {}))
    for zid, z in archives.items():
        summary = z.get('summary_inline') or z.get('internal_summary')
        if summary is None:
            sf = z.get('summary_file')
            if isinstance(sf, dict) and sf.get('url'):
                summary = fetch_json(sf['url'], ctx)
        if summary:
            files.update(summary.get('files', {}))
    return {'files': files, 'tag_dictionary': {norm(k): v for k, v in d.get('tag_dictionary', {}).items()},
            'default_filter': (d.get('default_options') or {}).get('filter')}


# ---------------------------------------------------------------- filter logic (mirrors Downloader)

def effective_filter(db, global_filter, default_filter):
    result = global_filter
    if default_filter is not None:
        if global_filter is None or '[mister]' in default_filter.lower():
            result = default_filter
    if db['filter'] is not None:
        result = db['filter']
    if result is None:
        return ''
    result = result.lower()
    if '[mister]' in result:
        result = result.replace('[mister]', (global_filter or '').lower()).strip()
    return result


def uses_global(db, default_filter):
    """True when a term added to [mister] filter reaches this database."""
    if db['filter'] is not None:
        return '[mister]' in db['filter'].lower()
    if default_filter is not None:
        return '[mister]' in default_filter.lower()
    return True


class Filter:
    def __init__(self, text, tag_dict, tag_names_in_db):
        self.none = text in ('', 'all')
        self.all = text == '!all'
        self.pos, self.neg = [], []
        if self.none or self.all:
            return
        positive_all = False
        for part in text.split():
            neg = part.startswith('!')
            t = norm(part[1:] if neg else part)
            if t == 'all' and not neg:
                positive_all = True
                continue
            key = tag_dict.get(t, t)
            if neg:
                if key in tag_names_in_db:
                    self.neg.append(key)
            else:
                self.pos.append(key)
        essential = tag_dict.get('essential', 'essential')
        if self.pos and essential not in self.pos and essential not in self.neg:
            self.pos.append(essential)
        if positive_all:
            self.pos = []

    def excluded(self, tags):
        if self.none:
            return False
        if self.all:
            return True
        if self.pos and not any(p in tags for p in self.pos):
            return True
        return any(n in tags for n in self.neg)


# ---------------------------------------------------------------- analysis

def core_stem(p):
    """'_Arcade/cores/Qix_20261114.rbf' -> '_arcade/cores/qix' (folder + name without the date)."""
    p = strip_path(p).lower()
    if p.endswith('.rbf'):
        p = p[:-4]
    return re.sub(r'_\d{8}[^/]*$', '', p)


def strip_path(p):
    return p[1:] if p.startswith('|') else p


def categorize(paths):
    rbfs = [p for p in paths if p.lower().endswith('.rbf')]
    for p in rbfs:
        top = p.split('/')[0].lower()
        if top in CORE_FOLDERS:
            return CORE_FOLDERS[top]
    if rbfs:
        return 'Other'
    if any(p.lower().endswith('.mra') for p in paths):
        return 'Arcade'
    if any(p.lower().startswith('scripts/') for p in paths):
        return 'Scripts'
    return None  # extras: auto-approved


def label_for(term, paths):
    rbfs = sorted(os.path.basename(p) for p in paths if p.lower().endswith('.rbf'))
    mras = [p for p in paths if p.lower().endswith('.mra')]
    sh = sorted(os.path.basename(p) for p in paths if p.lower().startswith('scripts/'))
    if rbfs:
        name = re.sub(r'_\d{8}.*$', '', rbfs[0][:-4])
    elif sh:
        name = sh[0]
    elif mras:
        # no core file in the group: name it after the first game, e.g. "Narc (15kHz) (rev 7.00)"
        name = sorted(os.path.basename(p)[:-4] for p in mras if '/_alternatives/' not in p)[:1] or \
            [os.path.basename(mras[0])[:-4]]
        name = name[0]
    else:
        name = term
    extra = []
    if len(rbfs) > 1:
        extra.append('%d cores' % len(rbfs))
    if mras:
        extra.append('%d game%s' % (len(mras), '' if len(mras) == 1 else 's'))
    if not extra:
        extra.append('core' if rbfs else '%d file%s' % (len(paths), '' if len(paths) == 1 else 's'))
    return '%s (%s)' % (name, ', '.join(extra))


def analyze(progress=print):
    global_filter, dbs = load_databases()
    with open(STORE, encoding='utf-8') as f:
        store = json.load(f).get('dbs', {})
    ctx = ssl_context()
    results, errors = {}, []
    progress('Checking %d databases...' % len(dbs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(fetch_db, db, ctx): db for db in dbs}
        for fut in concurrent.futures.as_completed(futs):
            db = futs[fut]
            try:
                results[db['id']] = fut.result()
            except Exception as e:
                errors.append('%s: %s' % (db['section'], e))

    updates, auto_new, unblockable, core_additions = [], [], [], []
    installed_stems = {core_stem(p) for s in store.values() for p in s.get('files', {})
                       if p.lower().endswith('.rbf')}
    new_entries = []          # (scope, db, path, tagnames:set)
    protected = {}            # scope -> set of tag names on installed files
    installed_by_tag = {}     # (scope, tag) -> set of installed paths carrying that tag
    shared_raw = []           # (scope, db, path, tagnames, category) new content whose tags are all shared
    for db in dbs:
        r = results.get(db['id'])
        if r is None:
            continue
        td = r['tag_dictionary']
        rev = {v: k for k, v in td.items()}
        names_in_db = set()
        for desc in r['files'].values():
            names_in_db.update(desc.get('tags', []))
        flt = Filter(effective_filter(db, global_filter, r['default_filter']), td, names_in_db)
        stored = store.get(db['id'], {}).get('files', {})
        scope = 'global' if uses_global(db, r['default_filter']) else db['id']
        prot = protected.setdefault(scope, set())
        for raw, desc in r['files'].items():
            p = strip_path(raw)
            tags = desc.get('tags', [])
            tagnames = {norm(rev.get(t, t)) for t in tags}
            installed = p in stored or raw in stored
            if installed:
                prot.update(tagnames)
                for t in tagnames:
                    installed_by_tag.setdefault((scope, t), set()).add(p)
                if not flt.excluded(tags) and desc.get('hash') and stored.get(p, stored.get(raw, {})).get('hash') != desc.get('hash'):
                    updates.append((db['section'], p))
                continue
            if flt.excluded(tags):
                continue
            if os.path.exists(os.path.join(BASE, p)):
                prot.update(tagnames)  # present on disk already (hand-installed): treat as installed
                for t in tagnames:
                    installed_by_tag.setdefault((scope, t), set()).add(p)
                continue
            new_entries.append((scope, db, p, tagnames))

    # the [mister] terms already protect against everything any global db has installed;
    # a db-specific scope must also respect what that db has installed (already in its own set).
    # Group new files by the safe tag with the widest reach (prefer tags that cover a core .rbf).
    coverage = {}
    for scope, db, p, tagnames in new_entries:
        for t in tagnames:
            coverage.setdefault((scope, t), []).append(p)
    items = {}
    for scope, db, p, tagnames in new_entries:
        safe = [t for t in tagnames if t not in protected.get(scope, set())
                and t != 'essential' and TERM_RE.match(t)]
        if scope != 'global' and db['id'] in UA_OWNED_FILTER_DBS:
            safe = []
        if not safe:
            cat = categorize([p])
            if cat and not (p.lower().endswith('.rbf') and core_stem(p) in installed_stems):
                shared_raw.append((scope, db, p, tagnames, cat))  # new content, but its tags are shared: warn
            elif cat:
                core_additions.append((db['section'], p))        # new dated version of an installed core
            else:
                auto_new.append((db['section'], p, None))
            continue
        best = max(safe, key=lambda t: (any(x.lower().endswith('.rbf') for x in coverage[(scope, t)]),
                                        len(coverage[(scope, t)]), t))
        it = items.setdefault((scope, best), {'scope': scope, 'term': best, 'paths': [], 'dbs': set(),
                                             'db_meta': db})
        it['paths'].append(p)
        it['dbs'].add(db['section'])

    review, auto_items = [], []
    for it in items.values():
        it['category'] = categorize(it['paths'])
        it['label'] = label_for(it['term'], it['paths'])
        it['all_tag_paths'] = coverage[(it['scope'], it['term'])]
        it['action'] = 'block'  # 'install' | 'block' | 'defer'
        (review if it['category'] else auto_items).append(it)
    for it in auto_items:
        for p in it['paths']:
            auto_new.append((', '.join(sorted(it['dbs'])), p, None))
    review.sort(key=lambda i: (CATEGORY_ORDER.index(i['category']), i['label'].lower()))

    # Shared-tag content: offer "block + delete" using the tag that would delete the FEWEST installed
    # files. Default action is install.
    shared = {}
    for scope, db, p, tagnames, cat in shared_raw:
        cands = [t for t in tagnames if t != 'essential' and TERM_RE.match(t)]
        if scope != 'global' and db['id'] in UA_OWNED_FILTER_DBS:
            cands = []
        if not cands:
            unblockable.append((db['section'], p, cat))
            continue
        best = min(cands, key=lambda t: (len(installed_by_tag.get((scope, t), ())),
                                         -len(coverage.get((scope, t), ())), t))
        it = shared.setdefault((scope, best), {'scope': scope, 'term': best, 'paths': [], 'dbs': set(),
                                              'db_meta': db, 'shared': True, 'action': 'install'})
        it['paths'].append(p)
        it['dbs'].add(db['section'])
    shared_items = []
    for it in shared.values():
        it['category'] = categorize(it['paths']) or 'Other'
        it['label'] = label_for(it['term'], it['paths'])
        it['installed'] = sorted(installed_by_tag.get((it['scope'], it['term']), ()))
        shared_items.append(it)
    shared_items.sort(key=lambda i: (CATEGORY_ORDER.index(i['category']), i['label'].lower()))

    # files that would be hit by each term (used for conflict checks)
    tags_by_path = {}
    for scope, db, p, tagnames in new_entries:
        tags_by_path[(scope, p)] = tagnames
    return {'global_filter': global_filter, 'dbs': dbs, 'errors': errors, 'updates': updates,
            'auto_new': auto_new, 'unblockable': unblockable, 'core_additions': core_additions,
            'review': review, 'shared': shared_items,
            'tags_by_path': tags_by_path}


def all_items(a):
    return a['review'] + a['shared']


def by_action(a, action):
    return [i for i in all_items(a) if i['action'] == action]


def conflicts(a):
    """Items to install whose files would be filtered by a term we are about to block or defer."""
    blocked = [i for i in all_items(a) if i['action'] != 'install']
    out = []
    for keep in by_action(a, 'install'):
        for b in blocked:
            if b['scope'] != keep['scope']:
                continue
            hit = [p for p in keep['paths'] if b['term'] in a['tags_by_path'].get((keep['scope'], p), ())]
            if hit:
                out.append((keep, b, hit))
    return out


def scope_location(it):
    if it['scope'] == 'global':
        return MAIN_INI, 'MiSTer'
    db = it['db_meta']
    return db['ini'], db['section']


def delete_installed(it):
    """Delete the installed files carrying a shared item's tag. Returns (deleted, failed)."""
    deleted, failed = [], []
    for p in it.get('installed', []):
        full = os.path.normpath(os.path.join(BASE, p))
        if not full.startswith(BASE + '/'):
            continue
        try:
            if os.path.isfile(full):
                os.remove(full)
                deleted.append(p)
        except OSError as e:
            failed.append('%s (%s)' % (p, e))
    return deleted, failed


def apply_blocks(a):
    blocked = by_action(a, 'block')
    deferred = by_action(a, 'defer')
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    os.makedirs(CONF_DIR, exist_ok=True)
    # Record deferred terms BEFORE writing them, so an interrupted run can still release them.
    if deferred:
        pending = load_deferred()
        for it in deferred:
            path, section = scope_location(it)
            pending.append({'term': it['term'], 'ini': path, 'section': section, 'label': it['label']})
        save_json(DEFERRED, pending)
    by_loc = {}
    for it in blocked + deferred:
        by_loc.setdefault(scope_location(it), []).append(it['term'])
    for (path, section), terms in by_loc.items():
        add_filter_terms(path, section, sorted(set(terms)))
    deletions = []
    for it in blocked:
        if it.get('shared'):
            deleted, failed = delete_installed(it)
            it['deleted'] = len(deleted)
            deletions.append((it, deleted, failed))
    subprocess.run(['sync'])
    state = load_state()
    for it in blocked:
        path, section = scope_location(it)
        state[it['term'] + '@' + section.lower()] = {'term': it['term'], 'ini': path, 'section': section,
                                                     'label': it['label'], 'category': it['category'],
                                                     'dbs': sorted(it['dbs']), 'date': now,
                                                     'deleted_files': it.get('deleted', 0)}
    save_state(state)
    with open(HISTORY, 'a', encoding='utf-8') as f:
        f.write('%s  installed: %s\n' % (now, ', '.join(i['label'] for i in by_action(a, 'install')) or '-'))
        f.write('%s  blocked:   %s\n' % (now, ', '.join('%s [!%s]' % (i['label'], i['term']) for i in blocked) or '-'))
        f.write('%s  deferred:  %s\n' % (now, ', '.join('%s [!%s]' % (i['label'], i['term']) for i in deferred) or '-'))
        for it, deleted, failed in deletions:
            f.write('%s  deleted for !%s: %d files\n' % (now, it['term'], len(deleted)))
            for p in deleted:
                f.write('      - %s\n' % p)
            for p in failed:
                f.write('      ! could not delete %s\n' % p)
    return deletions


def load_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    save_json(STATE, state)


def save_json(path, data):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def load_deferred():
    try:
        with open(DEFERRED, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def release_deferred():
    """Remove the temporary deferred terms from the filter. Nothing was installed for them, so
    nothing is deleted; the items show up as new again next run. Returns the number of failures."""
    pending = load_deferred()
    if not pending:
        return 0
    by_loc, failed = {}, []
    for e in pending:
        by_loc.setdefault((e['ini'], e['section']), []).append(e)
    for (path, section), entries in by_loc.items():
        try:
            remove_filter_terms(path, section, [e['term'] for e in entries])
        except Exception as ex:  # keep it in the file so the next run retries
            print('WARNING: could not release deferred terms in %s [%s]: %s' % (path, section, ex))
            failed += entries
    if failed:
        save_json(DEFERRED, failed)
    else:
        os.remove(DEFERRED)
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    released = [e for e in pending if e not in failed]
    if released:
        with open(HISTORY, 'a', encoding='utf-8') as f:
            f.write('%s  released deferred: %s\n' % (now, ', '.join('%s [!%s]' % (e['label'], e['term'])
                                                                       for e in released)))
    subprocess.run(['sync'])
    return len(failed)


# ---------------------------------------------------------------- dialog UI

def dlg(args):
    r = subprocess.run(['dialog', '--backtitle', BACKTITLE] + args, stderr=subprocess.PIPE)
    return r.returncode, r.stderr.decode('utf-8', 'replace').strip()


def menu(title, text, items, default=None, ok='Select', cancel='Back'):
    args = ['--title', title, '--ok-label', ok, '--cancel-label', cancel]
    if default is not None:
        args += ['--default-item', default]
    args += ['--menu', text, '0', '0', '0']
    for tag, label in items:
        args += [tag, label]
    rc, out = dlg(args)
    return out if rc == 0 else None


def msgbox(title, text):
    dlg(['--title', title, '--msgbox', text, '0', '0'])


def yesno(title, text, default_no=False, yes='Yes', no='No'):
    args = ['--title', title, '--yes-label', yes, '--no-label', no]
    if default_no:
        args.append('--defaultno')
    rc, _ = dlg(args + ['--yesno', text, '0', '0'])
    return rc == 0


def textbox(title, text):
    with tempfile.NamedTemporaryFile('w', delete=False, suffix='.txt', encoding='utf-8') as f:
        f.write(text)
        name = f.name
    dlg(['--title', title, '--exit-label', 'Back', '--textbox', name, '0', '0'])
    os.remove(name)


MARKS = {'install': '[Install]', 'block': '[Block]  ', 'defer': '[Defer]  '}
NEXT_ACTION = {'install': 'block', 'block': 'defer', 'defer': 'install'}
BULK_KEYS = {'+': 'install', '-': 'block', '~': 'defer'}


def mark(it):
    return MARKS[it['action']]


def category_menu(a, cat):
    items = [i for i in a['review'] if i['category'] == cat]
    cursor = None
    while True:
        entries = [('+', 'Install ALL %s' % cat), ('-', 'Block ALL %s' % cat), ('~', 'Defer ALL %s' % cat)]
        for n, it in enumerate(items):
            entries.append((str(n + 1), '%s %s  {%s}' % (mark(it), it['label'], ', '.join(sorted(it['dbs'])))))
        entries.append(('D', 'Done'))
        choice = menu('%s - new' % cat,
                      'Install = download now    Block = add to the downloader.ini filter for good\n'
                      'Defer = not now, ask again next run\n'
                      'Press Enter on an item to switch it: Install -> Block -> Defer.', entries, default=cursor)
        if choice is None or choice == 'D':
            return
        cursor = choice
        if choice in BULK_KEYS:
            for it in items:
                it['action'] = BULK_KEYS[choice]
        else:
            it = items[int(choice) - 1]
            it['action'] = NEXT_ACTION[it['action']]


def summary_text(a):
    out = []
    out.append('AUTOMATIC (no approval needed)')
    out.append('  Updates to installed files: %d' % len(a['updates']))
    by_db = {}
    for db, p in a['updates']:
        by_db.setdefault(db, []).append(p)
    for db in sorted(by_db):
        out.append('    %s: %d' % (db, len(by_db[db])))
        for p in sorted(by_db[db])[:40]:
            out.append('      ' + p)
        if len(by_db[db]) > 40:
            out.append('      ... and %d more' % (len(by_db[db]) - 40))
    out.append('')
    out.append('  New versions of cores you already have: %d' % len(a['core_additions']))
    for db, p in sorted(a['core_additions'])[:200]:
        out.append('    [%s] %s' % (db, p))
    out.append('')
    out.append('  New extras (wallpapers, MGLs, manuals, BIOS, docs...): %d' % len(a['auto_new']))
    for db, p, _ in sorted(a['auto_new'])[:200]:
        out.append('    [%s] %s' % (db, p))
    if len(a['auto_new']) > 200:
        out.append('    ... and %d more' % (len(a['auto_new']) - 200))
    if a['shared']:
        out.append('')
        out.append('SHARED-TAG CONTENT (installs unless set to "Block + delete" in the W menu)')
        for it in a['shared']:
            out.append('  %s: %s  !%s' % (it['category'], it['label'], it['term']))
            for p in sorted(it['paths']):
                out.append('    new:    %s' % p)
            for p in it['installed'][:30]:
                out.append('    delete: %s' % p)
            if len(it['installed']) > 30:
                out.append('    ... and %d more installed files' % (len(it['installed']) - 30))
    if a['unblockable']:
        out.append('')
        out.append('  WARNING - new content with no tag that can be blocked at all.')
        out.append('  Exit without updating if you do not want these:')
        for db, p, cat in sorted(a['unblockable']):
            out.append('    [%s] %s' % (db, p))
    if a['errors']:
        out.append('')
        out.append('  DATABASES THAT COULD NOT BE CHECKED:')
        for e in a['errors']:
            out.append('    ' + e)
    return '\n'.join(out) + '\n'


def unblock_menu():
    while True:
        state = load_state()
        if not state:
            msgbox('Blocked cores', 'Nothing has been blocked by this script yet.')
            return
        keys = sorted(state, key=lambda k: (state[k].get('category', ''), state[k]['label'].lower()))
        entries = [(str(n + 1), '%-9s %s  (!%s, %s)' % (state[k].get('category', ''), state[k]['label'],
                                                         state[k]['term'], state[k].get('date', '')))
                   for n, k in enumerate(keys)]
        choice = menu('Blocked cores', 'Pick one to UNBLOCK (removes it from the downloader.ini filter).\n'
                      'An unblocked core is installed by this update run.', entries)
        if choice is None:
            return
        k = keys[int(choice) - 1]
        e = state[k]
        if yesno('Unblock', 'Unblock %s?\n\nRemoves !%s from [%s] in\n%s' % (e['label'], e['term'], e['section'], e['ini']),
                 default_no=True):
            remove_filter_terms(e['ini'], e['section'], [e['term']])
            state.pop(k)
            save_state(state)


def filter_menu(a):
    """The 'add to filter' menu: review everything set to block; switch any to install or defer."""
    while True:
        blocked = [i for i in a['review'] if i['action'] == 'block']
        if not blocked:
            msgbox('Add to filter', 'No new core/script is set to BLOCK - nothing will be added to the filter for good.')
            return
        entries = [(str(n + 1), '%-9s %s  -> !%s' % (it['category'], it['label'], it['term']))
                   for n, it in enumerate(blocked)]
        choice = menu('Add to filter (%d)' % len(blocked),
                      'These will be added to the downloader.ini filter when you continue,\n'
                      'so they never show again. Press Enter on one to change it.', entries)
        if choice is None:
            return
        it = blocked[int(choice) - 1]
        act = menu(it['label'], 'What should happen to %s?' % it['label'],
                   [('I', 'Install it'), ('L', 'Defer it - ask again next run'), ('B', 'Keep it blocked')])
        if act == 'I':
            it['action'] = 'install'
        elif act == 'L':
            it['action'] = 'defer'


def shared_menu(a):
    """New content whose tags are all shared with installed files: install (default) or block + delete."""
    items = a['shared']
    cursor = None
    while True:
        entries = []
        for n, it in enumerate(items):
            state = 'INSTALL' if it['action'] == 'install' else 'BLOCK + DELETE %d' % len(it['installed'])
            entries.append((str(n + 1), '%-18s %s  (!%s)' % (state, it['label'], it['term'])))
        entries.append(('D', 'Done'))
        choice = menu('Shared-tag content (%d)' % len(items),
                      'These share their tag with files you already have, so blocking them\n'
                      'also DELETES those installed files. Enter switches install / block + delete.\n'
                      '(Defer is not possible here: filtering them even for one run deletes those files.)',
                      entries, default=cursor)
        if choice is None or choice == 'D':
            return
        cursor = choice
        it = items[int(choice) - 1]
        if it['action'] != 'install':
            it['action'] = 'install'
            continue
        listing = ['  ' + p for p in it['installed'][:15]]
        if len(it['installed']) > 15:
            listing.append('  ... and %d more' % (len(it['installed']) - 15))
        if yesno('Block + delete: %s' % it['label'],
                 'Blocking !%s will DELETE these %d installed files:\n\n%s\n\n'
                 'and stop the %d new file(s) from installing. The tag is added to the\n'
                 'downloader.ini filter. Deletion happens when you continue to Update All.\n\n'
                 'Block and delete?' % (it['term'], len(it['installed']), '\n'.join(listing) or '  (none)',
                                        len(it['paths'])),
                 default_no=True, yes='Delete', no='Keep'):
            it['action'] = 'block'


def confirm_and_apply(a):
    hits = conflicts(a)
    if hits:
        lines = ['These selections clash - a blocked/deferred tag also covers files of an installed item:', '']
        for keep, b, paths in hits[:12]:
            lines.append('%s  <-  %s !%s (%s)' % (keep['label'], 'deferring' if b['action'] == 'defer' else 'blocking',
                                                  b['term'], b['label']))
        lines += ['', 'Give both the same choice, then try again.']
        msgbox('Conflict', '\n'.join(lines))
        return False
    inst = by_action(a, 'install')
    blk = [i for i in a['review'] if i['action'] == 'block']
    dfr = [i for i in a['review'] if i['action'] == 'defer']
    dele = [i for i in a['shared'] if i['action'] == 'block']
    text = ['INSTALL (%d):' % len(inst)] + ['  %s: %s' % (i['category'], i['label']) for i in inst[:20]]
    if len(inst) > 20:
        text.append('  ... and %d more' % (len(inst) - 20))
    text += ['', 'BLOCK permanently - add to downloader.ini filter (%d):' % len(blk)]
    text += ['  %s: %s' % (i['category'], i['label']) for i in blk[:20]]
    if len(blk) > 20:
        text.append('  ... and %d more' % (len(blk) - 20))
    if dfr:
        text += ['', 'DEFER - not installed, asked again next run (%d):' % len(dfr)]
        text += ['  %s: %s' % (i['category'], i['label']) for i in dfr[:20]]
        if len(dfr) > 20:
            text.append('  ... and %d more' % (len(dfr) - 20))
    if dele:
        text += ['', 'BLOCK + DELETE installed files (%d):' % len(dele)]
        text += ['  %s: %s - deletes %d files' % (i['category'], i['label'], len(i['installed'])) for i in dele]
    text += ['', 'Plus %d updates, %d new versions of installed cores and %d new extras (automatic).' % (
        len(a['updates']), len(a['core_additions']), len(a['auto_new'])), '', 'Continue to Update All?']
    if not yesno('Confirm', '\n'.join(text), yes='Continue', no='Back'):
        return False
    deletions = apply_blocks(a)  # filter + deletions + history.log
    failed = [f for _, _, fl in deletions for f in fl]
    if failed:
        msgbox('Some files could not be deleted', '\n'.join(failed[:15]) +
               '\n\nThey are filtered, so Downloader will remove them during the update.')
    return True


def run_ui():
    os.system('clear')
    # Items deferred last time are still filtered if Update All was interrupted (or rebooted)
    # before the launcher could release them: release them first so they are offered again.
    if load_deferred():
        print('Releasing items deferred last run...', flush=True)
        if release_deferred():
            msgbox('Deferred items', 'Some deferred items could not be released from the filter.\n'
                   'They stay hidden this run; see %s.' % DEFERRED)
    a = analyze(progress=lambda s: print(s, flush=True))
    if a['errors'] and not yesno('Some databases could not be checked',
                                 'Could not check:\n  ' + '\n  '.join(a['errors'][:10]) +
                                 '\n\nUpdate All may install new items from these databases without asking.\n'
                                 'Continue anyway?', default_no=True):
        return 1
    if a['shared'] or a['unblockable']:
        shown = ['  %s  (blocking deletes %d installed files)' % (i['label'], len(i['installed']))
                 for i in a['shared'][:12]]
        if len(a['shared']) > 12:
            shown.append('  ... and %d more' % (len(a['shared']) - 12))
        shown += ['  [%s] %s  (no tag to block)' % (db, p) for db, p, _ in sorted(a['unblockable'])[:6]]
        if not yesno('Warning: content shares tags with installed files',
                     'This new content carries only tags that installed files also carry.\n'
                     'It installs unless you choose "Block + delete" in the Shared-tag menu,\n'
                     'which also deletes the installed files with that tag:\n\n' +
                     '\n'.join(shown) + '\n\nContinue to the review menus?', yes='Continue', no='Exit'):
            return 1
    cursor = None
    while True:
        entries = []
        for cat in CATEGORY_ORDER:
            its = [i for i in a['review'] if i['category'] == cat]
            if its:
                n = {k: sum(1 for i in its if i['action'] == k) for k in MARKS}
                note = ' (scripts need approval)' if cat == 'Scripts' else ''
                entries.append((str(CATEGORY_ORDER.index(cat) + 1),
                                '%-9s %3d new: %3d install %3d block %3d defer%s' % (
                                    cat, len(its), n['install'], n['block'], n['defer'], note)))
        if a['shared']:
            ndel = sum(1 for i in a['shared'] if i['action'] == 'block')
            entries.append(('W', 'Shared-tag content: %d new, %d set to block + delete' % (len(a['shared']), ndel)))
        if a['review']:
            nblk = sum(1 for i in a['review'] if i['action'] == 'block')
            entries += [('*', 'Install ALL new cores + scripts'),
                        ('/', 'Block ALL new cores + scripts'),
                        ('~', 'Defer ALL new cores + scripts (ask again next run)'),
                        ('F', 'Add to filter: %d will be blocked (review)' % nblk)]
        entries += [('A', 'Show automatic changes (%d)' % (len(a['updates']) + len(a['core_additions']) + len(a['auto_new']))),
                    ('U', 'Unblock a previously blocked core'),
                    ('G', 'Continue to Update All'),
                    ('X', 'Exit without updating')]
        tags = {e[0]: e for e in entries}
        text = ('New items are NOT installed unless you pick them.\n'
                'Block = added to the downloader.ini filter for good.  Defer = ask again next run.')
        if not a['review']:
            text = 'No new cores or scripts to approve.'
        choice = menu('New cores and scripts', text, entries, default=cursor, cancel='Exit')
        if choice is None or choice == 'X':
            if yesno('Exit', 'Exit without updating? Nothing will be installed, blocked or deleted.', default_no=False):
                return 1
            continue
        cursor = choice
        cat_by_key = {str(n + 1): c for n, c in enumerate(CATEGORY_ORDER)}
        if choice in cat_by_key and choice in tags:
            category_menu(a, cat_by_key[choice])
        elif choice == 'W':
            shared_menu(a)
        elif choice in ('*', '/', '~'):
            for i in a['review']:
                i['action'] = {'*': 'install', '/': 'block', '~': 'defer'}[choice]
        elif choice == 'F':
            filter_menu(a)
        elif choice == 'A':
            textbox('Automatic changes', summary_text(a))
        elif choice == 'U':
            unblock_menu()
        elif choice == 'G':
            if confirm_and_apply(a):
                return 0


def report():
    pending = load_deferred()
    if pending:
        print('NOTE: %d deferred term(s) are still in the filter (released at the next interactive run): %s'
              % (len(pending), ', '.join('!' + e['term'] for e in pending)))
    a = analyze()
    print('Global filter terms: %d' % len((a['global_filter'] or '').split()))
    print('Databases: %d (errors: %d)' % (len(a['dbs']), len(a['errors'])))
    for e in a['errors']:
        print('  ERROR ' + e)
    print('Updates to installed files: %d' % len(a['updates']))
    print('New extras (auto): %d' % len(a['auto_new']))
    print('New versions of installed cores (auto): %d' % len(a['core_additions']))
    print('SHARED-TAG content (installs unless block + delete): %d' % len(a['shared']))
    for it in a['shared']:
        print('  %-9s %-40s !%-22s new %d, would delete %d: %s' % (
            it['category'], it['label'][:40], it['term'], len(it['paths']), len(it['installed']),
            ', '.join(it['installed'][:3])))
    print('No tag at all to block: %d' % len(a['unblockable']))
    for db, p, c in sorted(a['unblockable'])[:30]:
        print('   [%s] %s' % (db, p))
    print('NEW ITEMS NEEDING APPROVAL: %d' % len(a['review']))
    for it in a['review']:
        loc = scope_location(it)
        print('  %-9s %-50s !%-20s [%s] %s' % (it['category'], it['label'][:50], it['term'],
                                              loc[1], ', '.join(sorted(it['dbs']))))
    return 0


def main():
    if '--report' in sys.argv:
        return report()
    if '--release-deferred' in sys.argv:
        return 2 if release_deferred() else 0
    if not shutil.which('dialog'):
        print('dialog is not installed; cannot show the review menus.')
        return 2
    try:
        return run_ui()
    except KeyboardInterrupt:
        return 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        print('\nCheck First failed (%s). Update All was NOT run.' % e)
        sys.exit(2)
