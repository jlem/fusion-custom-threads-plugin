import adsk.core
import adsk.fusion
import adsk.cam
import os
import re
import shutil
import struct
import zlib
import xml.etree.ElementTree as ET
from xml.dom import minidom
from pathlib import Path

# ── Toolbar icon ──────────────────────────────────────────────────────────────

def _make_icon_png(size, variant='add'):
    """
    Generate a size×size PNG toolbar icon.
    Both variants share a blue background with a white bold 'M'.
      variant='add'    – adds a '+' in the lower-right area
      variant='manage' – adds a pencil stroke in the lower-right area
    Pure Python — no Pillow or other image library required.
    """
    BG = (26, 115, 232)   # #1A73E8 — Autodesk-ish blue
    FG = (255, 255, 255)  # white

    buf = [BG] * (size * size)

    def put(x, y):
        if 0 <= x < size and 0 <= y < size:
            buf[y * size + x] = FG

    def fill(x0, y0, x1, y1):
        for yy in range(y0, y1 + 1):
            for xx in range(x0, x1 + 1):
                put(xx, yy)

    def line(x0, y0, x1, y1, t):
        """Bresenham line with square-cap thickness t."""
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err, x, y, h = dx - dy, x0, y0, t // 2
        while True:
            for oy in range(-h, h + 1):
                for ox in range(-h, h + 1):
                    put(x + ox, y + oy)
            if x == x1 and y == y1:
                break
            e2 = err * 2
            if e2 > -dy: err -= dy; x += sx
            if e2 <  dx: err += dx; y += sy

    # All coordinates are defined on a 32×32 reference grid and scaled.
    def sc(v):
        return max(0, int(round(v * size / 32)))

    t = max(2, sc(3))   # M stroke thickness

    # ── M (identical in both variants) ──────────────────────────────────────
    fill(sc(3),  sc(4), sc(6),  sc(27))              # left vertical bar
    fill(sc(25), sc(4), sc(28), sc(27))              # right vertical bar
    line(sc(7),  sc(4), sc(15), sc(15), t)           # left diagonal
    line(sc(16), sc(15), sc(24), sc(4), t)           # right diagonal

    # ── Variant symbol (lower-right area, between the M's verticals) ────────
    if variant == 'add':
        # Plus sign: horizontal and vertical bars forming '+'
        fill(sc(16), sc(23), sc(29), sc(26))         # horizontal bar
        fill(sc(21), sc(17), sc(25), sc(29))         # vertical bar

    elif variant == 'manage':
        # Pencil: diagonal body, eraser block, pointed tip
        line(sc(28), sc(17), sc(19), sc(26), max(1, sc(2)))   # body
        fill(sc(17), sc(26), sc(20), sc(29))         # tip (writing point)
        fill(sc(27), sc(15), sc(30), sc(19))         # eraser end

    # ── PNG encode (IHDR + IDAT + IEND) ─────────────────────────────────────
    def chunk(tag, data):
        body = tag + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    raw = bytearray()
    for row in range(size):
        raw += b'\x00'
        for col in range(size):
            raw += bytes(buf[row * size + col])

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(bytes(raw)))
            + chunk(b'IEND', b''))


def _ensure_icons():
    """
    Write 16×16 and 32×32 PNGs for each icon variant into the bundle's
    resources folder.  Returns {'add': path, 'manage': path}.
    Each variant is regenerated if its directory is missing.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    paths = {}
    for variant in ('add', 'manage'):
        icon_dir = os.path.join(script_dir, 'resources', variant)
        os.makedirs(icon_dir, exist_ok=True)
        for size in (16, 32):
            path = os.path.join(icon_dir, f'{size}x{size}.png')
            if not os.path.exists(path):
                with open(path, 'wb') as fh:
                    fh.write(_make_icon_png(size, variant))
        paths[variant] = icon_dir
    return paths


# ── Locate Fusion's active ThreadData folder ──────────────────────────────────

def get_fusion_thread_dir():
    """
    Derive the path to Fusion's ThreadData folder from the running app's
    resource folder, which already contains the correct version hash.

    Typical result:
      C:/Users/<user>/AppData/Local/Autodesk/webdeploy/production/<hash>
        /Fusion/Server/Fusion/Configuration/ThreadData
    """
    app = adsk.core.Application.get()
    resource_folder = (
        app.userInterface
           .workspaces.itemById('FusionSolidEnvironment')
           .resourceFolder
           .replace('\\', '/')
    )
    # resource_folder ends with …/Fusion/UI/FusionUI/Resources/Environment/Model
    # Walk back to the deploy root (everything up to and including the version hash)
    match = re.match(r'(.*?/webdeploy/(?:pre-)?production/[^/]+)', resource_folder)
    if not match:
        raise RuntimeError(f'Cannot parse deploy folder from: {resource_folder}')
    deploy_root = match.group(1)
    return Path(deploy_root) / 'Fusion' / 'Server' / 'Fusion' / 'Configuration' / 'ThreadData'


# ── ThreadKeeper backup folder ───────────────────────────────────────────────

def get_threadkeeper_backup_dir():
    """
    Return the ThreadKeeper Threads directory used as its persistent backup.
    ThreadKeeper syncs everything in this folder back to Fusion's ThreadData
    on every startup, so placing our file here makes it survive Fusion updates.
    """
    path = (Path(os.path.expandvars('%AppData%'))
            / 'Autodesk' / 'ApplicationPlugins'
            / 'ThreadKeeper.bundle' / 'Contents' / 'Threads')
    path.mkdir(parents=True, exist_ok=True)
    return path


# ── ISO metric thread geometry ────────────────────────────────────────────────
#
# Dimension formulas are derived by fitting against ISOMetricprofile.xml
# (Autodesk's own thread data file).  Each tolerance class stores a single
# representative value (mid-point of the tolerance band) per diameter.
#
# Verified against M3x0.5, M6x1, M10x0.75, M10x1, M10x1.5.

THREAD_FILE_NAME = 'Custom Metric.xml'


def calc_metric_thread(d, p):
    """
    Calculate thread dimensions matching Fusion 360's ISOMetricprofile.xml format.
    d = nominal diameter (mm), p = pitch (mm).
    Produces three Thread entries: 6g external, 6H internal, 4g6g external.
    """
    # ── Basic ISO 68-1 geometry ──────────────────────────────────────────────
    d2 = d - 0.64952 * p    # basic pitch diameter
    D1 = d - 1.08253 * p    # basic internal minor diameter
    d3 = d - 1.22687 * p    # basic external minor diameter
    tap = round(d - p, 4)   # tap drill = d - p  (matches all entries in profile)

    # ── 6g external (mid-point of tolerance band, fitted to profile data) ────
    d_6g  = round(d  - 0.116  * p ** 0.670, 4)   # major diameter
    d2_6g = round(d2 - 0.0818 * p ** 0.438, 4)   # pitch diameter
    d3_6g = round(d3,                        4)   # minor diameter ≈ basic

    # ── 6H internal (mid-point of tolerance band, fitted to profile data) ────
    D_6H  = round(d  + 0.147  * p ** 0.776, 4)   # major diameter
    D2_6H = round(d2 + 0.0753 * p ** 0.448, 4)   # pitch diameter
    D1_6H = round(D1 + 0.118  * p ** 0.594, 4)   # minor diameter

    # ── 4g6g external (tighter than 6g; pitch dia offset is ~75.5% of 6g) ───
    d_4g6g  = d_6g                                         # same major as 6g
    d2_4g6g = round(d2 - 0.0619 * p ** 0.438, 4)          # pitch diameter
    d3_4g6g = round(d3,                        4)          # minor ≈ basic

    return {
        'designation': f'M{d:g}x{p:g}',
        'size': d,
        'pitch': p,
        'tap_drill': tap,
        '6g':   {'major': d_6g,   'pitch': d2_6g,   'minor': d3_6g,   'gender': 'external'},
        '6H':   {'major': D_6H,   'pitch': D2_6H,   'minor': D1_6H,   'gender': 'internal', 'tap': tap},
        '4g6g': {'major': d_4g6g, 'pitch': d2_4g6g, 'minor': d3_4g6g, 'gender': 'external'},
    }


def build_thread_xml(threads):
    """
    Build a Fusion 360 ThreadType XML tree that matches the structure of
    ISOMetricprofile.xml exactly, including Gender tags on every Thread entry.
    """
    root = ET.Element('ThreadType')
    ET.SubElement(root, 'Name').text = 'Custom Metric'
    ET.SubElement(root, 'CustomName').text = 'Custom Metric'
    ET.SubElement(root, 'Unit').text = 'mm'
    ET.SubElement(root, 'Angle').text = '60'
    ET.SubElement(root, 'SortOrder').text = '3'

    for t in threads:
        ts = ET.SubElement(root, 'ThreadSize')
        ET.SubElement(ts, 'Size').text = str(float(t['size']))

        desig = ET.SubElement(ts, 'Designation')
        ET.SubElement(desig, 'ThreadDesignation').text = t['designation']
        ET.SubElement(desig, 'CTD').text = t['designation']
        if t.get('label'):
            ET.SubElement(desig, 'Label').text = t['label']
        ET.SubElement(desig, 'Pitch').text = str(t['pitch'])

        for cls in ('6g', '6H', '4g6g'):
            dims = t[cls]
            thread = ET.SubElement(desig, 'Thread')
            ET.SubElement(thread, 'Gender').text = dims['gender']
            ET.SubElement(thread, 'Class').text = cls
            ET.SubElement(thread, 'MajorDia').text = str(dims['major'])
            ET.SubElement(thread, 'PitchDia').text = str(dims['pitch'])
            ET.SubElement(thread, 'MinorDia').text = str(dims['minor'])
            if 'tap' in dims:
                ET.SubElement(thread, 'TapDrill').text = str(dims['tap'])

    return root


def load_existing_threads(filepath):
    """Return list of (diameter, pitch, label) tuples from the thread XML file."""
    if not filepath.exists():
        return []
    root = ET.parse(str(filepath)).getroot()
    threads = []
    for ts in root.findall('ThreadSize'):
        size = float(ts.find('Size').text)
        for desig in ts.findall('Designation'):
            pitch_el = desig.find('Pitch')
            if pitch_el is not None:
                label_el = desig.find('Label')
                label = (label_el.text or '').strip() if label_el is not None else ''
                threads.append((size, float(pitch_el.text), label))
    return threads


def apply_changes(deletes, new_d=None, new_p=None, new_label=''):
    """
    Apply a batch of changes to Custom Metric.xml in one write:
      - deletes   : set of (d, p) tuples to remove (matched by diameter+pitch)
      - new_d/p   : optional new thread to add
      - new_label : optional human-readable label stored in <Label> (ignored by Fusion)

    Returns (filepath_str, added_bool, backup_path_or_None).
    Nothing is written if there are no effective changes.
    """
    thread_dir = get_fusion_thread_dir()
    filepath   = thread_dir / THREAD_FILE_NAME
    existing   = load_existing_threads(filepath)   # [(d, p, label), ...]

    def matches(a, b):
        return abs(a[0] - b[0]) < 0.001 and abs(a[1] - b[1]) < 0.001

    remaining = [t for t in existing
                 if not any(matches(t, d) for d in deletes)]

    added = False
    if new_d is not None and new_p is not None and new_d > 0 and new_p > 0:
        if not any(matches((new_d, new_p), t) for t in remaining):
            remaining.append((new_d, new_p, new_label or ''))
            added = True

    if not deletes and not added:
        return str(filepath), False, None

    # Sort by diameter then pitch for a tidy file
    remaining.sort(key=lambda t: (t[0], t[1]))

    thread_data = []
    for d, p, lbl in remaining:
        t = calc_metric_thread(d, p)
        t['label'] = lbl
        thread_data.append(t)

    xml_root = build_thread_xml(thread_data)
    xml_str  = minidom.parseString(
        ET.tostring(xml_root, encoding='unicode')
    ).toprettyxml(indent='  ')
    clean = '\n'.join(line for line in xml_str.splitlines() if line.strip())

    with open(str(filepath), 'w', encoding='utf-8') as f:
        f.write(clean)

    backup_path = None
    try:
        backup_file = get_threadkeeper_backup_dir() / THREAD_FILE_NAME
        shutil.copy2(str(filepath), str(backup_file))
        backup_path = str(backup_file)
    except Exception:
        pass

    return str(filepath), added, backup_path


# ── Shared dialog helpers ─────────────────────────────────────────────────────

def make_preview(d_str, p_str):
    try:
        d = float(d_str.strip())
        p = float(p_str.strip())
        if d > 0 and p > 0:
            t = calc_metric_thread(d, p)
            return (
                f"Designation : {t['designation']}\n"
                f"Pitch dia   : {t['6H']['pitch']} mm\n"
                f"Minor dia   : {t['6H']['minor']} mm  (6H internal)\n"
                f"Tap drill   : {t['tap_drill']} mm\n"
                f"Classes     : 6g (external/bolt)  +  6H (internal/nut)  +  4g6g"
            )
    except Exception:
        pass
    return 'Enter a valid diameter and pitch to preview.'


def _result_message(filepath, backup_path, parts):
    backup_line = (f'Backup:  {backup_path}' if backup_path
                   else 'Backup:  ThreadKeeper folder not found — skipped.')
    return ('\n'.join(parts)
            + f'\n\nPrimary: {filepath}\n{backup_line}'
            + '\n\nRestart Fusion 360 to apply changes in the Thread tool.')


# ── "Add Thread" dialog ───────────────────────────────────────────────────────

class AddCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            cmd    = adsk.core.Command.cast(args.command)
            inputs = cmd.commandInputs
            inputs.addStringValueInput('add_d',     'Nominal Diameter (mm)', '10')
            inputs.addStringValueInput('add_p',     'Pitch (mm)',            '1.5')
            inputs.addStringValueInput('add_label', 'Label (optional)',      '')
            inputs.addTextBoxCommandInput('add_preview', 'Thread Info',
                                          make_preview('10', '1.5'), 5, True)
            h = AddChangedHandler();  cmd.inputChanged.add(h); _handlers.append(h)
            h = AddExecuteHandler();  cmd.execute.add(h);      _handlers.append(h)
        except Exception as e:
            adsk.core.Application.get().userInterface.messageBox(f'Dialog error: {e}')


class AddChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        try:
            if args.input.id in ('add_d', 'add_p'):
                inputs  = args.inputs
                d_str   = inputs.itemById('add_d').value
                p_str   = inputs.itemById('add_p').value
                inputs.itemById('add_preview').text = make_preview(d_str, p_str)
        except Exception:
            pass


class AddExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        ui = adsk.core.Application.get().userInterface
        try:
            inputs = adsk.core.Command.cast(args.command).commandInputs
            d     = float(inputs.itemById('add_d').value.strip())
            p     = float(inputs.itemById('add_p').value.strip())
            label = inputs.itemById('add_label').value.strip()
            if d <= 0 or p <= 0:
                ui.messageBox('Diameter and pitch must be positive numbers.')
                return
            filepath, added, backup = apply_changes(set(), d, p, label)
            if added:
                ui.messageBox(_result_message(filepath, backup,
                                              [f'Thread M{d:g}x{p:g} added.']))
            else:
                ui.messageBox(f'M{d:g}x{p:g} is already in the custom library.')
        except ValueError:
            ui.messageBox('Please enter numeric values for diameter and pitch.')
        except Exception as e:
            ui.messageBox(f'Error saving thread: {e}')


# ── "Manage Threads" dialog ───────────────────────────────────────────────────
#
# Design principle: the table is built ONCE when the dialog opens and is
# NEVER deleted or rebuilt during the session.  Instead, cell text is updated
# in-place (via table.commandInputs.itemById) so we never touch the input list
# from inside an inputChanged callback — the root cause of the previous bugs.
#
# _manage_threads  : (d, p) list — the threads shown when the dialog opened
# _pending_deletes : set of (d, p) to remove on OK
# _edit_index      : index into _manage_threads of the row being edited, or -1

_manage_threads  = []
_pending_deletes = set()
_edit_index      = -1


def _set_row_label(inputs, i, text):
    """Update the designation cell text for row i without rebuilding the table."""
    try:
        table = inputs.itemById('mgr_table')
        if table:
            cell = table.commandInputs.itemById(f'mgr_desig_{i}')
            if cell:
                cell.text = text
    except Exception:
        pass


class ManageCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        global _manage_threads, _pending_deletes, _edit_index
        _pending_deletes = set()
        _edit_index      = -1
        try:
            fp = get_fusion_thread_dir() / THREAD_FILE_NAME
            _manage_threads = load_existing_threads(fp)
        except Exception:
            _manage_threads = []

        try:
            cmd    = adsk.core.Command.cast(args.command)
            inputs = cmd.commandInputs

            # ── Table (built once, never rebuilt) ───────────────────────────
            table = inputs.addTableCommandInput('mgr_table', 'Custom Threads', 5, '4:3:2:1:1')
            table.minimumVisibleRows = 3
            table.maximumVisibleRows = 8
            table.isFullWidth = True
            ti = table.commandInputs

            table.addCommandInput(ti.addTextBoxCommandInput('mgr_h0', '', 'Designation',    1, True), 0, 0)
            table.addCommandInput(ti.addTextBoxCommandInput('mgr_h1', '', 'Label',          1, True), 0, 1)
            table.addCommandInput(ti.addTextBoxCommandInput('mgr_h2', '', 'Tap Drill (mm)', 1, True), 0, 2)
            table.addCommandInput(ti.addTextBoxCommandInput('mgr_h3', '', 'Edit',           1, True), 0, 3)
            table.addCommandInput(ti.addTextBoxCommandInput('mgr_h4', '', 'Remove',         1, True), 0, 4)

            if not _manage_threads:
                empty = ti.addTextBoxCommandInput('mgr_empty', '',
                                                  'No custom threads defined yet.', 1, True)
                table.addCommandInput(empty, 1, 0, 1, 5)
            else:
                for i, (d, p, lbl) in enumerate(_manage_threads):
                    t   = calc_metric_thread(d, p)
                    row = i + 1
                    table.addCommandInput(
                        ti.addTextBoxCommandInput(f'mgr_desig_{i}', '', t['designation'],    1, True), row, 0)
                    table.addCommandInput(
                        ti.addTextBoxCommandInput(f'mgr_label_{i}', '', lbl,                 1, True), row, 1)
                    table.addCommandInput(
                        ti.addTextBoxCommandInput(f'mgr_tap_{i}',   '', str(t['tap_drill']), 1, True), row, 2)
                    table.addCommandInput(
                        ti.addBoolValueInput(f'mgr_edit_{i}', 'Edit',   False, '', False), row, 3)
                    table.addCommandInput(
                        ti.addBoolValueInput(f'mgr_rem_{i}',  'Remove', False, '', False), row, 4)

            # ── Edit fields (always present below the table) ─────────────────
            inputs.addStringValueInput('mgr_d',     'Nominal Diameter (mm)', '')
            inputs.addStringValueInput('mgr_p',     'Pitch (mm)',            '')
            inputs.addStringValueInput('mgr_label', 'Label (optional)',      '')
            inputs.addTextBoxCommandInput('mgr_preview', 'Thread Info',
                                          'Click Edit on a row to modify it.', 4, True)

            h = ManageChangedHandler(); cmd.inputChanged.add(h); _handlers.append(h)
            h = ManageExecuteHandler(); cmd.execute.add(h);      _handlers.append(h)

        except Exception as e:
            adsk.core.Application.get().userInterface.messageBox(f'Dialog error: {e}')


class ManageChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        global _pending_deletes, _edit_index
        try:
            cid    = args.input.id
            inputs = args.inputs

            if cid.startswith('mgr_edit_'):
                i        = int(cid.split('_')[-1])
                d, p, lbl = _manage_threads[i]
                t         = calc_metric_thread(d, p)

                # Clear the previous edit marker if switching rows
                if _edit_index >= 0 and _edit_index != i:
                    d_prev, p_prev, _ = _manage_threads[_edit_index]
                    orig = calc_metric_thread(d_prev, p_prev)['designation']
                    _set_row_label(inputs, _edit_index, orig)

                _edit_index = i
                _set_row_label(inputs, i, f'→ {t["designation"]}')
                inputs.itemById('mgr_d').value       = f'{d:g}'
                inputs.itemById('mgr_p').value       = f'{p:g}'
                inputs.itemById('mgr_label').value   = lbl
                inputs.itemById('mgr_preview').text  = make_preview(f'{d:g}', f'{p:g}')

            elif cid.startswith('mgr_rem_'):
                i         = int(cid.split('_')[-1])
                d, p, lbl = _manage_threads[i]
                _pending_deletes.add((d, p))
                _set_row_label(inputs, i, f'[removed] {calc_metric_thread(d, p)["designation"]}')
                # If the removed row was being edited, clear the edit state
                if _edit_index == i:
                    _edit_index = -1
                    inputs.itemById('mgr_d').value      = ''
                    inputs.itemById('mgr_p').value      = ''
                    inputs.itemById('mgr_label').value  = ''
                    inputs.itemById('mgr_preview').text = 'Click Edit on a row to modify it.'

            elif cid in ('mgr_d', 'mgr_p'):
                d_str = inputs.itemById('mgr_d').value
                p_str = inputs.itemById('mgr_p').value
                inputs.itemById('mgr_preview').text = make_preview(d_str, p_str)

        except Exception:
            pass


class ManageExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self): super().__init__()

    def notify(self, args):
        ui = adsk.core.Application.get().userInterface
        try:
            inputs   = adsk.core.Command.cast(args.command).commandInputs
            deletes  = set(_pending_deletes)
            new_d, new_p, new_label = None, None, ''

            if _edit_index >= 0:
                d_str = inputs.itemById('mgr_d').value.strip()
                p_str = inputs.itemById('mgr_p').value.strip()
                if d_str and p_str:
                    d_orig, p_orig, _ = _manage_threads[_edit_index]
                    deletes.add((d_orig, p_orig))          # delete the original
                    new_d     = float(d_str)
                    new_p     = float(p_str)
                    new_label = inputs.itemById('mgr_label').value.strip()

            filepath, added, backup = apply_changes(deletes, new_d, new_p, new_label)

            parts = []
            if added:
                d_o, p_o, _ = _manage_threads[_edit_index]
                parts.append(f'M{d_o:g}x{p_o:g} updated to M{new_d:g}x{new_p:g}.')
            n_removed = len(_pending_deletes)   # excludes the edit-replacement
            if n_removed:
                parts.append(f'{n_removed} thread(s) removed.')

            if parts:
                ui.messageBox(_result_message(filepath, backup, parts))

        except ValueError:
            ui.messageBox('Please enter numeric values for diameter and pitch.')
        except Exception as e:
            ui.messageBox(f'Error applying changes: {e}')


# ── Fusion 360 event handlers — GC anchors ────────────────────────────────────

_handlers = []
_panel    = None


# ── Add-in entry points ───────────────────────────────────────────────────────

def _get_panel(ui):
    try:
        return (ui.workspaces
                  .itemById('FusionSolidEnvironment')
                  .toolbarTabs
                  .itemById('ToolsTab')
                  .toolbarPanels
                  .itemById('customMetricThreadPanel'))
    except Exception:
        return None


def _register_cmd(ui, cmd_id, label, tooltip, icon_dir):
    """Delete any stale definition and register a fresh one. Returns the CommandDefinition."""
    old = ui.commandDefinitions.itemById(cmd_id)
    if old:
        old.deleteMe()
    return ui.commandDefinitions.addButtonDefinition(cmd_id, label, tooltip, icon_dir)


def run(context):
    global _panel
    ui = None
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        panel = _get_panel(ui)
        if panel:
            panel.deleteMe()

        icons = _ensure_icons()

        # ── Add Thread command ───────────────────────────────────────────────
        add_def = _register_cmd(ui,
            'customMetricAddCmd',
            'Add Custom Metric Thread',
            'Define a new custom ISO metric thread.\n\n'
            'Tip: right-click to assign a keyboard shortcut.',
            icons['add'])
        h = AddCreatedHandler()
        add_def.commandCreated.add(h)
        _handlers.append(h)

        # ── Manage Threads command ───────────────────────────────────────────
        mgr_def = _register_cmd(ui,
            'customMetricManageCmd',
            'Manage Custom Metric Threads',
            'Edit or remove existing custom metric threads.',
            icons['manage'])
        h = ManageCreatedHandler()
        mgr_def.commandCreated.add(h)
        _handlers.append(h)

        # ── Toolbar panel with both buttons ──────────────────────────────────
        tools_tab = (ui.workspaces
                       .itemById('FusionSolidEnvironment')
                       .toolbarTabs
                       .itemById('ToolsTab'))
        _panel = tools_tab.toolbarPanels.add('customMetricThreadPanel', 'Custom Threads')

        for cmd_def in (add_def, mgr_def):
            ctrl = _panel.controls.addCommand(cmd_def)
            ctrl.isPromoted         = True
            ctrl.isPromotedByDefault = True

    except Exception as e:
        if ui:
            ui.messageBox(f'Failed to start: {e}')


def stop(context):
    global _panel
    try:
        app = adsk.core.Application.get()
        ui  = app.userInterface

        panel = _get_panel(ui)
        if panel:
            panel.deleteMe()
        _panel = None

        for cmd_id in ('customMetricAddCmd', 'customMetricManageCmd'):
            cmd_def = ui.commandDefinitions.itemById(cmd_id)
            if cmd_def:
                cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        pass
