# Scripted UI test: fakes every dialog call and writes only to copies under /tmp/ucf_test.
# Run on the MiSTer:  python3 tests/test_ui_block.py   (set UCF_DIR if ucf.py is elsewhere)
# Flow: continue past the warning (if shown) -> Computer: install all, untick #1 -> view automatic
# changes -> filter menu: switch the first blocked item to install -> continue + confirm.
# Needs at least one new Computer core in the current databases.
import configparser
import os
import shutil
import sys

UCF_DIR = os.environ.get('UCF_DIR', '/media/fat/Scripts/.config/update_all_check_first')
WORK = '/tmp/ucf_test'
os.makedirs(WORK, exist_ok=True)
sys.dont_write_bytecode = True  # keep the helper folder clean
sys.path.insert(0, UCF_DIR)
import ucf  # noqa: E402

shutil.copy('/media/fat/downloader.ini', WORK + '/test_downloader.ini')
ucf.MAIN_INI = WORK + '/test_downloader.ini'
ucf.CONF_DIR = WORK + '/conf'
ucf.STATE = WORK + '/conf/blocked.json'
ucf.HISTORY = WORK + '/conf/history.log'
shutil.rmtree(ucf.CONF_DIR, ignore_errors=True)


def filter_terms():
    cp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'), interpolation=None)
    cp.read(ucf.MAIN_INI)
    return cp['mister'].get('filter', '').split() if cp.has_section('mister') else []


BEFORE = len(filter_terms())
script = [
    ('--menu', 0, '2'), ('--menu', 0, '+'), ('--menu', 0, '1'), ('--menu', 0, 'D'),
    ('--menu', 0, 'A'), ('--textbox', 0, ''),
    ('--menu', 0, 'F'), ('--menu', 0, '1'), ('--menu', 1, ''),
    ('--menu', 0, 'G'), ('--yesno', 0, ''),
]
log = []


def fake(args):
    kind = next(a for a in args if a in ('--menu', '--yesno', '--msgbox', '--textbox'))
    title = args[args.index('--title') + 1]
    log.append('%s %s' % (kind, title))
    if kind == '--msgbox':
        return 0, ''
    if kind == '--yesno' and title.startswith('Warning'):
        return 0, ''  # shared-tag warning: continue
    exp = script.pop(0)
    assert exp[0] == kind, (exp, kind, title)
    return exp[1], exp[2]


ucf.dlg = fake
os.system = lambda c: 0
rc = ucf.run_ui()
print('\n'.join(log))
print('RC', rc, 'script left', script)
print('added terms:', filter_terms()[BEFORE:])
print(open(ucf.HISTORY).read())
