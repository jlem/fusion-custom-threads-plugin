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

def _make_icon_png(size):
    """
    Generate a size×size PNG: blue background with a white bold 'M'.
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

    t = max(2, sc(3))  # stroke thickness

    fill(sc(3),  sc(4), sc(6),  sc(27))   # left vertical bar
    fill(sc(25), sc(4), sc(28), sc(27))   # right vertical bar
    line(sc(7),  sc(4), sc(15), sc(15), t)  # left diagonal  (top → V-point)
    line(sc(16), sc(15), sc(24), sc(4), t)  # right diagonal (V-point → top)

    # Encode as PNG (IHDR + IDAT + IEND)
    def chunk(tag, data):
        body = tag + data
        return (struct.pack('>I', len(data)) + body
                + struct.pack('>I', zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack('>IIBBBBB', size, size, 8, 2, 0, 0, 0)
    raw = bytearray()
    for row in range(size):
        raw += b'\x00'                          # filter byte: None
        for col in range(size):
            raw += bytes(buf[row * size + col])

    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(bytes(raw)))
            + chunk(b'IEND', b''))


def _ensure_icons():
    """
    Write 16×16 and 32×32 icon PNGs into the bundle's resources folder.
    Returns the icon directory path (passed to addButtonDefinition).
    Icons are only generated if they don't already exist.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    icon_dir   = os.path.join(script_dir, 'resources', 'icon')
    os.makedirs(icon_dir, exist_ok=True)
    for size in (16, 32):
        path = os.path.join(icon_dir, f'{size}x{size}.png')
        if not os.path.exists(path):
            with open(path, 'wb') as fh:
                fh.write(_make_icon_png(size))
    return icon_dir


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
    """Return list of (diameter, pitch) tuples already in the thread XML file."""
    if not filepath.exists():
        return []
    root = ET.parse(str(filepath)).getroot()
    threads = []
    for ts in root.findall('ThreadSize'):
        size = float(ts.find('Size').text)
        for desig in ts.findall('Designation'):
            pitch_el = desig.find('Pitch')
            if pitch_el is not None:
                threads.append((size, float(pitch_el.text)))
    return threads


def save_thread(d, p):
    """
    Write thread M{d}x{p} into Custom Metric.xml in Fusion's ThreadData folder,
    then copy the file to the ThreadKeeper backup directory so it survives
    future Fusion updates.
    Returns (filepath_str, was_added, backup_filepath_str_or_None).
    """
    thread_dir = get_fusion_thread_dir()
    filepath = thread_dir / THREAD_FILE_NAME
    existing = load_existing_threads(filepath)

    if any(abs(ed - d) < 0.001 and abs(ep - p) < 0.001 for ed, ep in existing):
        return str(filepath), False, None

    all_threads = [calc_metric_thread(ed, ep) for ed, ep in existing]
    all_threads.append(calc_metric_thread(d, p))

    xml_root = build_thread_xml(all_threads)
    xml_str = minidom.parseString(
        ET.tostring(xml_root, encoding='unicode')
    ).toprettyxml(indent='  ')
    clean = '\n'.join(line for line in xml_str.splitlines() if line.strip())

    with open(str(filepath), 'w', encoding='utf-8') as f:
        f.write(clean)

    # Mirror to ThreadKeeper so the file is restored after any Fusion update
    backup_path = None
    try:
        backup_file = get_threadkeeper_backup_dir() / THREAD_FILE_NAME
        shutil.copy2(str(filepath), str(backup_file))
        backup_path = str(backup_file)
    except Exception:
        pass  # backup failure is non-fatal; primary write already succeeded

    return str(filepath), True, backup_path


# ── Dialog preview helper ─────────────────────────────────────────────────────

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
                f"Classes     : 6g (external/bolt)  +  6H (internal/nut)  +  4g6g (external)"
            )
    except Exception:
        pass
    return 'Enter numeric values to preview thread dimensions.'


# ── Fusion 360 event handlers ─────────────────────────────────────────────────

# Held at module level to prevent garbage collection between Fusion events.
_handlers = []
_panel = None


class CreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            cmd = adsk.core.Command.cast(args.command)
            inputs = cmd.commandInputs

            inputs.addStringValueInput('diameter', 'Nominal Diameter (mm)', '10')
            inputs.addStringValueInput('pitch', 'Pitch (mm)', '1.5')
            inputs.addTextBoxCommandInput(
                'preview', 'Thread Info',
                make_preview('10', '1.5'),
                5, True
            )

            h_changed = ChangedHandler()
            cmd.inputChanged.add(h_changed)
            _handlers.append(h_changed)

            h_exec = ExecuteHandler()
            cmd.execute.add(h_exec)
            _handlers.append(h_exec)

        except Exception as e:
            adsk.core.Application.get().userInterface.messageBox(f'Dialog error: {e}')


class ChangedHandler(adsk.core.InputChangedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            inputs = args.inputs
            d_str = inputs.itemById('diameter').value
            p_str = inputs.itemById('pitch').value
            preview = inputs.itemById('preview')
            if preview:
                preview.text = make_preview(d_str, p_str)
        except Exception:
            pass


class ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        ui = adsk.core.Application.get().userInterface
        try:
            cmd = adsk.core.Command.cast(args.command)
            inputs = cmd.commandInputs

            d = float(inputs.itemById('diameter').value.strip())
            p = float(inputs.itemById('pitch').value.strip())

            if d <= 0 or p <= 0:
                ui.messageBox('Diameter and pitch must be positive numbers.')
                return

            filepath, added, backup_path = save_thread(d, p)
            desig = f'M{d:g}x{p:g}'

            if added:
                backup_line = (f'Backup:  {backup_path}'
                               if backup_path else
                               'Backup:  ThreadKeeper folder not found — skipped.')
                ui.messageBox(
                    f'Thread {desig} added.\n\n'
                    f'Primary: {filepath}\n'
                    f'{backup_line}\n\n'
                    f'Restart Fusion 360 to use this thread in the Thread tool.'
                )
            else:
                ui.messageBox(f'Thread {desig} is already in the custom library.')

        except ValueError:
            ui.messageBox('Please enter numeric values for diameter and pitch.')
        except Exception as e:
            ui.messageBox(f'Error saving thread: {e}')


# ── Add-in entry points ───────────────────────────────────────────────────────

def _get_panel(ui):
    """Return the add-in's toolbar panel, or None if it doesn't exist yet."""
    try:
        return (ui.workspaces
                  .itemById('FusionSolidEnvironment')
                  .toolbarTabs
                  .itemById('ToolsTab')
                  .toolbarPanels
                  .itemById('customMetricThreadPanel'))
    except Exception:
        return None


def run(context):
    global _panel
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        # Clean up any state left over from a previous run without a clean stop
        panel = _get_panel(ui)
        if panel:
            panel.deleteMe()
        existing = ui.commandDefinitions.itemById('customMetricThreadCmd')
        if existing:
            existing.deleteMe()

        # Generate icons on first run, then register the command definition
        icon_dir = _ensure_icons()
        cmd_def = ui.commandDefinitions.addButtonDefinition(
            'customMetricThreadCmd',
            'Add Custom Metric Thread',
            'Add a custom ISO metric thread to the Fusion 360 thread library.\n\n'
            'Tip: right-click this button to assign a keyboard shortcut.',
            icon_dir
        )
        h_created = CreatedHandler()
        cmd_def.commandCreated.add(h_created)
        _handlers.append(h_created)

        # Add a persistent button to the Tools tab in the Design workspace,
        # matching the same location ThreadKeeper and similar add-ins use.
        tools_tab = (ui.workspaces
                       .itemById('FusionSolidEnvironment')
                       .toolbarTabs
                       .itemById('ToolsTab'))
        _panel = tools_tab.toolbarPanels.add(
            'customMetricThreadPanel', 'Custom Threads'
        )
        control = _panel.controls.addCommand(cmd_def)
        control.isPromoted = True          # show button text in the toolbar
        control.isPromotedByDefault = True # visible by default, not hidden in the panel

    except Exception as e:
        if ui:
            ui.messageBox(f'Failed to start: {e}')


def stop(context):
    global _panel
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface

        panel = _get_panel(ui)
        if panel:
            panel.deleteMe()
        _panel = None

        cmd_def = ui.commandDefinitions.itemById('customMetricThreadCmd')
        if cmd_def:
            cmd_def.deleteMe()
        _handlers.clear()
    except Exception:
        pass
