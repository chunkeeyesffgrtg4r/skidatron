import os
import sys
import time
import glob
import random
import string
import struct
import pefile
import shutil
import threading
import ctypes
import winreg

OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offsets_dump.txt")

def enable_ansi_windows():
    if os.name == 'nt':
        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        kernel32.GetStdHandle.argtypes = [ctypes.c_int]
        kernel32.GetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel32.SetConsoleMode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        hStdOut = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(hStdOut, ctypes.byref(mode)):
            mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(hStdOut, mode)

def safe_input(prompt: str) -> str:
    # KeyboardInterrupt bricht die Eingabe sicher ab, EOFError beendet das Programm
    try:
        return input(prompt)
    except KeyboardInterrupt:
        return ""
    except EOFError:
        sys.exit(0)

def start_title_scrambler():
    def scrambler():
        kernel32 = ctypes.windll.kernel32
        chars = string.ascii_letters + string.digits + "!@#$%^&*()_+-=[]{}|;:,.<>?"
        while True:
            rand_title = "".join(random.choices(chars, k=36))
            kernel32.SetConsoleTitleW(rand_title)
            time.sleep(0.025)

    t = threading.Thread(target=scrambler, daemon=True)
    t.start()

def hsv_to_rgb(h: float, s: float, v: float):
    h = h % 1.0
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i = i % 6
    if i == 0: r, g, b = v, t, p
    elif i == 1: r, g, b = q, v, p
    elif i == 2: r, g, b = p, v, t
    elif i == 3: r, g, b = p, q, v
    elif i == 4: r, g, b = t, p, v
    else: r, g, b = v, p, q
    return min(255, int(r * 255)), min(255, int(g * 255)), min(255, int(b * 255))

BANNER_LINES = [
    r"  $$$$$$\                         $$\             ",
    r" $$  __$$\                        $$ |            ",
    r" $$ /  \__|  $$$$$$\    $$$$$$\   $$ |   $$$$$$\  ",
    r" $$ |        \____$$\  $$  __$$\  $$ |  $$  __$$\ ",
    r" $$ |        $$$$$$$ | $$ |  \__| $$ |  $$ /  $$ |",
    r" $$ |       $$  __$$ | $$ |       $$ |  $$ |  $$ |",
    r" $$ |  $$\  $$  __$$ | $$ |       $$ |  $$ |  $$ |",
    r" \$$$$$$  | \$$$$$$$ | $$ |       $$ |  \$$$$$$  |",
    r"  \______/   \_______| \__|       \__|   \______/ "
]

def print_rainbow_banner():
    cols = shutil.get_terminal_size((80, 20)).columns
    total_lines = len(BANNER_LINES)
    max_len = max(len(line) for line in BANNER_LINES)
    pad = max(0, (cols - max_len) // 2)
    for idx, line in enumerate(BANNER_LINES):
        colored_line = ""
        for char_idx, char in enumerate(line):
            hue = (idx / total_lines * 0.35) + (char_idx / len(line) * 0.65)
            r, g, b = hsv_to_rgb(hue, 0.95, 1.0)
            colored_line += f"\033[38;2;{r};{g};{b}m{char}"

        print(" " * pad + colored_line + "\033[0m")

def render_centered_loading(duration_sec: float = 4.0):
    os.system("cls" if os.name == "nt" else "clear")
    size = shutil.get_terminal_size((80, 24))
    cols, rows = size.columns, size.lines

    top_pad = max(1, (rows // 2) - 2)
    sys.stdout.write("\n" * top_pad)

    bar_width = max(1, min(40, cols - 20))
    start_time = time.time()

    while True:
        elapsed = time.time() - start_time
        progress = min(1.0, elapsed / duration_sec)

        filled = int(progress * bar_width)
        empty = bar_width - filled

        bar_str = ""
        for i in range(filled):
            r, g, b = hsv_to_rgb(i / bar_width, 0.95, 1.0)
            bar_str += f"\033[38;2;{r};{g};{b}m="
        bar_str += "\033[90m" + "-" * empty + "\033[0m"

        percent = int(progress * 100)
        raw_len = bar_width + 7
        horiz_pad = max(0, (cols - raw_len) // 2)

        line_out = " " * horiz_pad + f"\033[1;37m[\033[0m{bar_str}\033[1;37m]\033[0m \033[1;32m{percent:>3}%\033[0m"
        sys.stdout.write(f"\r\033[K{line_out}")
        sys.stdout.flush()

        if progress >= 1.0:
            time.sleep(0.3)
            break
        time.sleep(0.02)

def get_latest_roblox_binary() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    search_path = os.path.join(local_app_data, "Roblox", "Versions", "version-*", "RobloxPlayerBeta.exe")
    files = glob.glob(search_path)
    if not files:
        return ""
    return max(files, key=os.path.getmtime)

def find_all_strings(rdata: bytes, image_base: int, rdata_rva: int, s: bytes):
    vas = []
    pos = 0
    while True:
        idx = rdata.find(s + b"\x00", pos)
        if idx == -1: break
        vas.append(image_base + rdata_rva + idx)
        pos = idx + 1
    return vas

def get_str_at_va(rdata: bytes, image_base: int, rdata_rva: int, va: int) -> str:
    offset = va - image_base - rdata_rva
    if 0 <= offset < len(rdata):
        end = rdata.find(b"\x00", offset)
        if end != -1:
            return rdata[offset:end].decode('utf-8', errors='ignore')
    return ""

_U64 = struct.Struct("<Q")
_unpack_q = _U64.unpack_from

# Descriptor pointer tables in RobloxPlayerBeta are runs of .data pointers in .rdata.
# Most of them are preceded by the QWord header (3, 4, 4, 0). We enumerate all runs once
# and assign them to classes afterwards (exclusive assignment, biggest class first) so two
# classes can never end up sharing the same table.
def enumerate_desc_segments(rdata: bytes, rdata_rva: int, data_min_va: int, data_max_va: int):
    segments = []  # (rva, n_ptrs, has_hdr, first_ptr)
    off = 0
    n = len(rdata)
    align = rdata_rva % 8
    while off + 8 <= n:
        p0 = _unpack_q(rdata, off)[0]
        if data_min_va <= p0 <= data_max_va:
            run_end = off
            while run_end + 8 <= n:
                p = _unpack_q(rdata, run_end)[0]
                if not (data_min_va <= p <= data_max_va):
                    break
                run_end += 8
            run_len = (run_end - off) // 8
            has_hdr = False
            if off >= 32:
                hdr = [_unpack_q(rdata, off - 32 + k * 8)[0] for k in range(4)]
                has_hdr = hdr == [3, 4, 4, 0]
            segments.append((rdata_rva + off, run_len, has_hdr, p0))
            off = run_end
        else:
            off += 8
    return segments

def locate_name_entries(rdata: bytes, image_base: int, rdata_rva: int, class_name: str, anchor_prop: str):
    """Find the 16-byte {class_name_ptr, prop_name_ptr} entry run for a class.
    Returns (start_idx, count, [(index, prop_name)]) or None."""
    class_vas = find_all_strings(rdata, image_base, rdata_rva, class_name.encode())
    anchor_vas = find_all_strings(rdata, image_base, rdata_rva, anchor_prop.encode())

    start_idx = -1
    matched_class_va = None
    for c_va in class_vas:
        for a_va in anchor_vas:
            idx = rdata.find(struct.pack("<QQ", c_va, a_va))
            if idx != -1:
                start_idx = idx
                matched_class_va = c_va
                break
        if start_idx != -1:
            break

    if start_idx == -1 or matched_class_va is None:
        return None

    while start_idx >= 16 and _unpack_q(rdata, start_idx - 16)[0] == matched_class_va:
        start_idx -= 16

    end_idx = start_idx
    while end_idx + 16 <= len(rdata) and _unpack_q(rdata, end_idx)[0] == matched_class_va:
        end_idx += 16

    count = (end_idx - start_idx) // 16
    if count <= 0:
        return None

    prop_names = []
    for i in range(count):
        ptr = _unpack_q(rdata, start_idx + i * 16 + 8)[0]
        name = get_str_at_va(rdata, image_base, rdata_rva, ptr)
        prop_names.append((i, name))
    return start_idx, count, prop_names

# Descriptor structs are 0xC0 bytes; descriptors of one class are allocated close
# together, so a huge spread means the segment does not belong to that class.
def segment_ptr_spread(rdata: bytes, rdata_rva: int, seg_rva: int, count: int) -> int:
    base = seg_rva - rdata_rva
    ptrs = [_unpack_q(rdata, base + i * 8)[0] for i in range(count)]
    return max(ptrs) - min(ptrs)

def assign_desc_table(rdata: bytes, rdata_rva: int, count: int, segments, used_rvas, warn_list, class_name: str):
    """Pick the best unused descriptor segment for a class with `count` members.
    Candidates whose first `count` pointers are scattered far wider than
    count * 0xC0 are rejected outright - a real class table is tightly packed.
    Among valid candidates prefer header-marked segments, the smallest length
    excess and the smallest pointer spread."""
    best = None
    best_key = None
    best_len = 0
    best_spread = 0
    for seg_rva, seg_len, has_hdr, _p0 in segments:
        if seg_rva in used_rvas or seg_len < count:
            continue
        spread = segment_ptr_spread(rdata, rdata_rva, seg_rva, count)
        if spread > count * 0xC0 * 2:
            continue  # scattered far beyond a plausible descriptor cluster
        key = (0 if has_hdr else 1, seg_len - count, spread)
        if best_key is None or key < best_key:
            best_key = key
            best = seg_rva
            best_len = seg_len
            best_spread = spread
    if best is None:
        return None
    used_rvas.add(best)
    return best

def dump_all_offsets(pe_path: str):
    if not pe_path or not os.path.exists(pe_path):
        print(f"\033[1;31m[-] File not found:\033[0m {pe_path}")
        return

    print(f"\033[1;34m[*]\033[0m Analyzing Binary: \033[37m{pe_path}\033[0m\n")
    try:
        pe = pefile.PE(pe_path, fast_load=False)
    except Exception as e:
        print(f"\033[1;31m[-] Failed to parse PE headers:\033[0m {e}")
        return

    if pe.FILE_HEADER.Machine != 0x8664:
        print(f"\033[1;31m[-] Not a 64-bit binary (Machine=0x{pe.FILE_HEADER.Machine:X}). "
              f"Offset layout assumptions only hold for x64.\033[0m")
        pe.close()
        return

    image_base = pe.OPTIONAL_HEADER.ImageBase

    rdata_sec = None
    data_sec = None
    for sec in pe.sections:
        name = sec.Name.decode(errors="ignore").strip("\x00")
        if name == ".rdata":
            rdata_sec = sec
        elif name == ".data":
            data_sec = sec

    if not rdata_sec or not data_sec:
        print("\033[1;31m[-] Required sections (.rdata, .data) not found in binary.\033[0m")
        pe.close()
        return

    rdata = rdata_sec.get_data()
    rdata_rva = rdata_sec.VirtualAddress
    data_rva = data_sec.VirtualAddress
    data_size = data_sec.Misc_VirtualSize
    data_min_va = image_base + data_rva
    data_max_va = data_min_va + data_size

    warn_list = []
    plain_lines = []
    out_file = None
    try:
        out_file = open(OUTPUT_FILE, "w", encoding="utf-8")
    except Exception as e:
        print(f"\033[1;33m[!]\033[0m Could not open {OUTPUT_FILE} for writing: {e}")

    def emit(plain: str, colored: str):
        print(colored)
        plain_lines.append(plain)
        if out_file:
            out_file.write(plain + "\n")

    # 1. WorldRoot::Raycast
    findparts_vas = find_all_strings(rdata, image_base, rdata_rva, b"FindPartsInRegion3")
    raycast_vas = find_all_strings(rdata, image_base, rdata_rva, b"Raycast")
    worldroot_vas = find_all_strings(rdata, image_base, rdata_rva, b"WorldRoot")

    wr_start_pair = -1
    matched_wr_va = None
    for w_va in worldroot_vas:
        for fp_va in findparts_vas:
            idx = rdata.find(struct.pack("<QQ", fp_va, w_va))
            if idx != -1:
                wr_start_pair = idx
                matched_wr_va = w_va
                break
        if wr_start_pair != -1:
            break

    wr_raycast_pair = -1
    if matched_wr_va is not None:
        for rc_va in raycast_vas:
            idx = rdata.find(struct.pack("<QQ", rc_va, matched_wr_va))
            if idx != -1:
                wr_raycast_pair = idx
                break

    wr_desc_rva = None
    if wr_start_pair != -1 and wr_raycast_pair != -1:
        wr_method_idx = (wr_raycast_pair - wr_start_pair) // 16
        if 0 <= wr_method_idx < 25:
            scan_limit = len(rdata) - 25 * 8
            for i in range(0, scan_limit, 8):
                ptrs = [_unpack_q(rdata, i + j * 8)[0] for j in range(4)]
                if data_min_va <= ptrs[0] <= data_max_va:
                    if (ptrs[1] - ptrs[0] == 0xC0) and (ptrs[2] - ptrs[1] == 0xC0) and (ptrs[0] - ptrs[3] == 0x400):
                        desc_ptr_offset = i + wr_method_idx * 8
                        if 0 <= desc_ptr_offset and desc_ptr_offset + 8 <= len(rdata):
                            desc_va = _unpack_q(rdata, desc_ptr_offset)[0]
                            if data_min_va <= desc_va <= data_max_va:
                                wr_desc_rva = desc_va - image_base
                                break
        else:
            warn_list.append(f"WorldRoot: Raycast method index {wr_method_idx} out of expected range (0-24), skipped")
    else:
        warn_list.append("WorldRoot: could not locate FindPartsInRegion3/Raycast member anchors in this build")

    # Dynamic Class Scanners (one shared segment pool, exclusive assignment)
    segments = enumerate_desc_segments(rdata, rdata_rva, data_min_va, data_max_va)
    used_rvas = set()

    class_requests = [
        ("BasePart", "Anchored"),
        ("Humanoid", "WalkSpeed"),
        ("Player", "Character"),
        ("Players", "LocalPlayer"),
        ("Workspace", "Gravity"),
        ("DataModel", "PlaceId"),
        ("Lighting", "Ambient"),
        ("Camera", "FieldOfView"),
        ("UserInputService", "AccelerometerEnabled"),
        ("ProximityPrompt", "HoldDuration"),
        ("SoundService", "AmbientReverb"),
        ("Stats", "ContactsCount"),
        ("GuiService", "MenuIsOpen"),
    ]

    scan_results = {}
    # Biggest classes claim their table first: they have the fewest viable segments,
    # which keeps the exclusive assignment unambiguous.
    located_classes = []
    for class_name, anchor in class_requests:
        loc = locate_name_entries(rdata, image_base, rdata_rva, class_name, anchor)
        located_classes.append((class_name, loc))
    for class_name, loc in sorted(located_classes, key=lambda x: -(x[1][1] if x[1] else 0)):
        if loc is None:
            scan_results[class_name] = (None, {})
            warn_list.append(f"{class_name}: member name table not found (class renamed or layout changed)")
            continue
        _start, count, _names = loc
        table_rva = assign_desc_table(rdata, rdata_rva, count, segments, used_rvas, warn_list, class_name)
        if table_rva is None:
            scan_results[class_name] = (None, {})
            warn_list.append(f"{class_name}: no free descriptor table with >= {count} pointers found")
            continue
        prop_descs = {}
        base = table_rva - rdata_rva
        for idx, name in loc[2]:
            desc_va = _unpack_q(rdata, base + idx * 8)[0]
            prop_descs[name] = (idx, desc_va - image_base)
        scan_results[class_name] = (table_rva, prop_descs)

    bp_table_rva, bp_descs = scan_results["BasePart"]
    hum_table_rva, hum_descs = scan_results["Humanoid"]
    plr_table_rva, plr_descs = scan_results["Player"]
    plrs_table_rva, plrs_descs = scan_results["Players"]
    ws_table_rva, ws_descs = scan_results["Workspace"]
    dm_table_rva, dm_descs = scan_results["DataModel"]
    lighting_table_rva, lighting_descs = scan_results["Lighting"]
    camera_table_rva, camera_descs = scan_results["Camera"]
    uis_table_rva, uis_descs = scan_results["UserInputService"]
    prox_table_rva, prox_descs = scan_results["ProximityPrompt"]
    snd_table_rva, snd_descs = scan_results["SoundService"]
    stats_table_rva, stats_descs = scan_results["Stats"]
    gui_table_rva, gui_descs = scan_results["GuiService"]

    # RaycastParams
    respect_vas = find_all_strings(rdata, image_base, rdata_rva, b"RespectCanCollide")
    ignorewater_vas = find_all_strings(rdata, image_base, rdata_rva, b"IgnoreWater")
    rp_tables = []
    for resp_va in respect_vas:
        pos = 0
        while True:
            idx = rdata.find(struct.pack("<Q", resp_va), pos)
            if idx == -1: break
            if idx >= 7 * 16 and (rdata_rva + idx) % 8 == 0:
                table_start_idx = idx - 7 * 16
                p0 = _unpack_q(rdata, table_start_idx)[0]
                if p0 in ignorewater_vas:
                    rp_tables.append(rdata_rva + table_start_idx)
            pos = idx + 1

    # Print Formatted Output
    emit("=" * 70, "\033[1;35m" + "=" * 70 + "\033[0m")
    emit("                    DUMPED OFFSETS (C++)                    ",
         "                    \033[1;32mDUMPED OFFSETS (C++)\033[0m                    ")
    emit("=" * 70, "\033[1;35m" + "=" * 70 + "\033[0m")

    def emit_namespace(title, comment, table_rva, descs, props):
        header = f"namespace {title} {{"
        if comment:
            header += f"  // {comment}"
        emit(header, f"\033[1;37mnamespace {title} {{\033[0m" + (f"  \033[90m// {comment}\033[0m" if comment else ""))
        if table_rva:
            emit(f"    inline constexpr uintptr_t PropDescTable         = {hex(table_rva)};",
                 f"    \033[36minline constexpr uintptr_t\033[0m \033[1;33mPropDescTable\033[0m         = \033[1;32m{hex(table_rva)}\033[0m;")
        else:
            emit(f"    // PropDescTable NOT FOUND - scan failed for this class",
                 f"    \033[1;31m// PropDescTable NOT FOUND - scan failed for this class\033[0m")
        found_any = False
        for prop in props:
            if prop in descs:
                found_any = True
                idx, rva = descs[prop]
                emit(f"    inline constexpr uintptr_t {prop:<24} = {hex(rva)};  // Index {idx}",
                     f"    \033[36minline constexpr uintptr_t\033[0m \033[1;33m{prop:<24}\033[0m = \033[1;32m{hex(rva)}\033[0m;  \033[90m// Index {idx}\033[0m")
        if not found_any:
            emit("    // (no requested properties found in this build)",
                 "    \033[90m// (no requested properties found in this build)\033[0m")
        emit("}", "\033[1;37m}\033[0m")

    emit("namespace WorldRoot {", "\033[1;37mnamespace WorldRoot {\033[0m")
    if wr_desc_rva:
        emit(f"    inline constexpr uintptr_t RaycastBoundDesc    = {hex(wr_desc_rva)};",
             f"    \033[36minline constexpr uintptr_t\033[0m \033[1;33mRaycastBoundDesc\033[0m    = \033[1;32m{hex(wr_desc_rva)}\033[0m;")
    else:
        emit("    // RaycastBoundDesc NOT FOUND in this build",
             "    \033[1;31m// RaycastBoundDesc NOT FOUND in this build\033[0m")
    emit("    inline constexpr uintptr_t RaycastBoundFn      = 0x80;  // hardcoded, verify manually after updates",
         f"    \033[36minline constexpr uintptr_t\033[0m \033[1;33mRaycastBoundFn\033[0m      = \033[1;32m0x80\033[0m;  \033[90m// hardcoded, verify manually after updates\033[0m")
    emit("}", "\033[1;37m}\033[0m")
    emit("", "")

    emit_namespace("BasePart", "Hitboxes, Physics & Collision", bp_table_rva, bp_descs,
                   ["CanCollide", "CanQuery", "CanTouch", "CollisionGroup", "Size", "Transparency",
                    "Velocity", "AssemblyLinearVelocity", "Position", "CFrame"])
    emit_namespace("Humanoid", "Movement, Health & Exploits", hum_table_rva, hum_descs,
                   ["WalkSpeed", "JumpPower", "JumpHeight", "HipHeight", "Health", "MaxHealth",
                    "RigType", "PlatformStand", "Sit", "AutoRotate", "CameraOffset", "MoveDirection",
                    "AutoJumpEnabled"])
    emit_namespace("ProximityPrompt", "Instant Interact / Auto-Rob / Reach", prox_table_rva, prox_descs,
                   ["HoldDuration", "MaxActivationDistance", "RequiresLineOfSight", "Enabled", "ClickablePrompt"])
    emit_namespace("Player", "Character & Team Verification", plr_table_rva, plr_descs,
                   ["Character", "Team", "TeamColor", "Neutral", "UserId", "AccountAge", "DisplayName",
                    "SimulationRadius"])
    emit_namespace("Players", "LocalPlayer & Player List", plrs_table_rva, plrs_descs,
                   ["LocalPlayer", "MaxPlayers", "NumPlayers", "RespawnTime"])
    emit_namespace("Workspace", "World Physics & Gravity", ws_table_rva, ws_descs,
                   ["Gravity", "FallenPartsDestroyHeight", "GlobalWind", "StreamingEnabled",
                    "StreamingMinRadius", "StreamingTargetRadius"])
    emit_namespace("Camera", "World: FOV, Stretched Res, Freecam, CFrame", camera_table_rva, camera_descs,
                   ["FieldOfView", "DiagonalFieldOfView", "MaxAxisFieldOfView", "FieldOfViewMode",
                    "CFrame", "CoordinateFrame", "Focus", "ViewportSize", "NearPlaneZ",
                    "CameraType", "CameraSubject", "HeadScale"])
    emit_namespace("Lighting", "Visuals: Ambient, Fullbright, Fog, Shadows", lighting_table_rva, lighting_descs,
                   ["Ambient", "OutdoorAmbient", "Brightness", "ClockTime", "TimeOfDay",
                    "ExposureCompensation", "Technology", "ShadowSoftness", "GlobalShadows",
                    "FogStart", "FogEnd", "FogColor", "EnvironmentDiffuseScale", "EnvironmentSpecularScale"])
    emit_namespace("UserInputService", "Device Spoofer", uis_table_rva, uis_descs,
                   ["TouchEnabled", "KeyboardEnabled", "MouseEnabled", "GamepadEnabled", "VREnabled",
                    "GyroscopeEnabled", "AccelerometerEnabled"])
    emit_namespace("GuiService", "Menu States & CoreGui", gui_table_rva, gui_descs,
                   ["MenuIsOpen", "AutoSelectGuiEnabled", "CoreGuiNavigationEnabled", "DisplayScalingMode",
                    "TopbarInset"])
    emit_namespace("Stats", "Performance & Ping Telemetry", stats_table_rva, stats_descs,
                   ["DataReceiveKbps", "DataSendKbps", "PhysicsReceiveKbps", "PhysicsSendKbps",
                    "HeartbeatTimeMs", "PhysicsStepTimeMs"])
    emit_namespace("SoundService", "Audio Occlusion & Reverb", snd_table_rva, snd_descs,
                   ["AmbientReverb", "DistanceFactor", "DopplerScale", "RolloffScale",
                    "RespectFilteringEnabled", "OcclusionEnabled"])
    emit_namespace("DataModel", "Game & Server Identification", dm_table_rva, dm_descs,
                   ["PlaceId", "GameId", "JobId", "CreatorId", "PrivateServerId", "Workspace", "lighting"])

    # RaycastParams (fixed member indices)
    emit("namespace RaycastParams {", "\033[1;37mnamespace RaycastParams {\033[0m")
    if len(rp_tables) >= 1:
        emit(f"    inline constexpr uintptr_t SetterTable      = {hex(rp_tables[0])};",
             f"    \033[36minline constexpr uintptr_t\033[0m \033[1;33mSetterTable\033[0m      = \033[1;32m{hex(rp_tables[0])}\033[0m;")
    if len(rp_tables) >= 2:
        emit(f"    inline constexpr uintptr_t GetterTable      = {hex(rp_tables[1])};",
             f"    \033[36minline constexpr uintptr_t\033[0m \033[1;33mGetterTable\033[0m      = \033[1;32m{hex(rp_tables[1])}\033[0m;")
    if not rp_tables:
        emit("    // Setter/Getter tables NOT FOUND in this build",
             "    \033[1;31m// Setter/Getter tables NOT FOUND in this build\033[0m")
    for name, val, note in [("IgnoreWater", 0, ""), ("FilterType", 1, ""), ("FilterDescendants", 2, ""),
                            ("CollisionGroup", 5, ""), ("RespectCanCollide", 7, "Wall-Penetration Switch")]:
        comment = f"  // {note}" if note else ""
        ccomment = f"  \033[90m// {note}\033[0m" if note else ""
        emit(f"    inline constexpr int {name:<19} = {val};{comment}",
             f"    \033[36minline constexpr int\033[0m       \033[1;33m{name:<19}\033[0m = \033[1;32m{val}\033[0m;{ccomment}")
    emit("}", "\033[1;37m}\033[0m")
    emit("=" * 70, "\033[1;35m" + "=" * 70 + "\033[0m")
    emit("", "")

    if warn_list:
        print("\n\033[1;33m[!] WARNINGS\033[0m")
        for w in warn_list:
            print(f"  \033[1;33m[!]\033[0m {w}")
        if out_file:
            out_file.write("\nWARNINGS:\n")
            for w in warn_list:
                out_file.write("  [!] " + w + "\n")

    pe.close()
    if out_file:
        out_file.close()
        print(f"\n\033[1;32m[+]\033[0m Dump written to \033[1;37m{OUTPUT_FILE}\033[0m")

def kill_roblox_processes():
    targets = [
        "RobloxPlayerBeta.exe",
        "RobloxPlayerLauncher.exe",
        "RobloxPlayerInstaller.exe",
        "RobloxCrashHandler.exe",
        "RobloxStudioBeta.exe",
        "RobloxStudioLauncherBeta.exe",
        "RobloxStudioInstaller.exe"
    ]
    for proc in targets:
        os.system(f"taskkill /F /IM {proc} >nul 2>&1")

def delete_path_safe(path: str):
    if not path:
        return
    if not os.path.exists(path):
        return
    self_path = os.path.abspath(sys.argv[0])
    if os.path.abspath(path) == self_path or os.path.abspath(path) == os.path.dirname(self_path):
        return

    try:
        if os.path.isfile(path) or os.path.islink(path):
            os.chmod(path, 0o777)
            os.remove(path)
            print(f"  \033[1;32m[+] Deleted file:\033[0m {path}")
        elif os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            print(f"  \033[1;32m[+] Deleted folder:\033[0m {path}")
    except Exception as e:
        print(f"  \033[1;31m[-] Could not delete {path}:\033[0m {e}")

def delete_registry_key_recursive(root, subkey):
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_ALL_ACCESS) as key:
            while True:
                try:
                    child = winreg.EnumKey(key, 0)
                    delete_registry_key_recursive(root, f"{subkey}\\{child}")
                except OSError:
                    break
        winreg.DeleteKey(root, subkey)
        print(f"  \033[1;32m[+] Deleted registry key:\033[0m {subkey}")
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"  \033[1;31m[-] Error deleting registry key {subkey}:\033[0m {e}")

def get_all_fixed_drives():
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in string.ascii_uppercase:
        if bitmask & 1:
            drive_path = f"{letter}:\\"
            dtype = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
            if dtype == 3:
                drives.append(drive_path)
        bitmask >>= 1
    return drives

def deep_clean_roblox():
    print("\033[1;35m" + "="*70 + "\033[0m")
    print("              \033[1;31mROBLOX DEEP CLEANER & PURGE\033[0m              ")
    print("\033[1;35m" + "="*70 + "\033[0m\n")

    print("\033[1;34m[*] Step 1:\033[0m Terminating active Roblox processes & installers...")
    kill_roblox_processes()
    time.sleep(0.5)

    print("\n\033[1;34m[*] Step 2:\033[0m Deleting primary Roblox directories & telemetry...")
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    appdata = os.environ.get("APPDATA", "")
    temp = os.environ.get("TEMP", "")
    userprofile = os.environ.get("USERPROFILE", "")
    prog_files = os.environ.get("ProgramFiles", "C:\\Program Files")
    prog_files_x86 = os.environ.get("ProgramFiles(x86)", "C:\\Program Files (x86)")
    prog_data = os.environ.get("ProgramData", "C:\\ProgramData")

    known_targets = []
    if local_appdata:
        known_targets += [os.path.join(local_appdata, "Roblox"),
                          os.path.join(local_appdata, "Roblox Studio")]
    if appdata:
        known_targets.append(os.path.join(appdata, "Roblox"))
    if temp:
        known_targets.append(os.path.join(temp, "Roblox"))
    if prog_data:
        known_targets.append(os.path.join(prog_data, "Roblox"))
    if prog_files:
        known_targets.append(os.path.join(prog_files, "Roblox"))
    if prog_files_x86:
        known_targets.append(os.path.join(prog_files_x86, "Roblox"))
    if userprofile:
        known_targets += [
            os.path.join(userprofile, "Documents", "Roblox"),
            os.path.join(userprofile, "Saved Games", "Roblox"),
            os.path.join(userprofile, "Desktop", "Roblox Player.lnk"),
            os.path.join(userprofile, "Desktop", "Roblox Studio.lnk"),
            os.path.join(userprofile, "AppData", "Roaming", "Microsoft", "Windows",
                         "Start Menu", "Programs", "Roblox"),
        ]

    for target in known_targets:
        delete_path_safe(target)

    crash_patterns = []
    if local_appdata:
        crash_patterns.append(os.path.join(local_appdata, "CrashDumps", "*Roblox*"))
    if temp:
        crash_patterns += [os.path.join(temp, "*Roblox*"), os.path.join(temp, "RBX-*")]
    for pattern in crash_patterns:
        for match in glob.glob(pattern):
            delete_path_safe(match)

    print("\n\033[1;34m[*] Step 3:\033[0m Purging Roblox Registry keys...")
    registry_targets = [
        (winreg.HKEY_CURRENT_USER, r"Software\ROBLOX Corporation"),
        (winreg.HKEY_CURRENT_USER, r"Software\Roblox"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\ROBLOX Corporation"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\ROBLOX Corporation"),
        (winreg.HKEY_CLASSES_ROOT, r"roblox"),
        (winreg.HKEY_CLASSES_ROOT, r"roblox-player"),
        (winreg.HKEY_CLASSES_ROOT, r"roblox-studio"),
        (winreg.HKEY_CURRENT_USER, r"Software\Classes\roblox-player"),
        (winreg.HKEY_CURRENT_USER, r"Software\Classes\roblox-studio"),
    ]
    for root, subkey in registry_targets:
        delete_registry_key_recursive(root, subkey)

    print("\n\033[1;34m[*] Step 4:\033[0m Purging Downloads, Desktop & installer files...")
    if not userprofile:
        userprofile = os.path.expanduser("~")
    download_folder = os.path.join(userprofile, "Downloads")
    desktop_folder = os.path.join(userprofile, "Desktop")

    installer_names = [
        "*Roblox*.exe",
        "*RobloxPlayer*.exe",
        "*RobloxStudio*.exe",
        "*RobloxPlayerInstaller*.exe",
        "*RobloxPlayerLauncher*.exe",
        "*RobloxStudioInstaller*.exe",
        "*RobloxStudioLauncher*.exe"
    ]

    for folder in [download_folder, desktop_folder]:
        if os.path.exists(folder):
            for pattern in installer_names:
                for match in glob.glob(os.path.join(folder, pattern)):
                    delete_path_safe(match)

    print("\n\033[1;34m[*] Step 5:\033[0m Deep-scanning all fixed drives for residual files & installers...")
    drives = get_all_fixed_drives()
    skip_dirs = {"$recycle.bin", "system volume information", "windows", "winsxs", "recovery", "appdata"}

    for drive in drives:
        print(f"  \033[90m[*] Scanning drive {drive}...\033[0m")
        try:
            for root, dirs, files in os.walk(drive, topdown=True):
                dirs[:] = [d for d in dirs if d.lower() not in skip_dirs and not d.startswith("$")]

                for d in list(dirs):
                    if d.lower() in ("roblox", "robloxcache", "roblox studio"):
                        full_dir = os.path.join(root, d)
                        delete_path_safe(full_dir)
                        dirs.remove(d)

                for f in files:
                    f_lower = f.lower()
                    if ("roblox" in f_lower) and (f_lower.endswith(".exe") or f_lower.endswith(".lnk") or f_lower.endswith(".dmp")):
                        full_file = os.path.join(root, f)
                        delete_path_safe(full_file)
        except Exception:
            pass

    print("\n\033[1;32m[+] Roblox Full System Deep Clean completed successfully!\033[0m\n")

def main():
    enable_ansi_windows()
    start_title_scrambler()

    render_centered_loading(duration_sec=4.0)

    os.system("cls" if os.name == "nt" else "clear")
    print("\n")
    print_rainbow_banner()
    print("\n" + "\033[90m" + "-"*70 + "\033[0m\n")

    while True:
        print("  \033[1;32m[1]\033[0m Dump Complete Engine & Cheat Offsets (Aimbot, ESP, Visuals, Exploits)")
        print("  \033[1;31m[2]\033[0m Roblox Deep Cleaner (Full PC Purge)")
        print("  \033[1;33m[q]\033[0m Quit\n")
        choice = safe_input("\033[1;33m[?]\033[0m Selection: ").strip()

        if choice.lower() == 'q':
            sys.exit(0)
        elif choice == '1':
            print("\n")
            target = get_latest_roblox_binary()
            if not target:
                target = safe_input("\033[1;33m[?]\033[0m Enter custom path to RobloxPlayerBeta.exe: ").strip('"')

            dump_all_offsets(target)
            print("\n")
            safe_input("\033[90mPress ENTER to continue...\033[0m")
            os.system("cls" if os.name == "nt" else "clear")
            print("\n")
            print_rainbow_banner()
            print("\n" + "\033[90m" + "-"*70 + "\033[0m\n")
        elif choice == '2':
            print("\n")
            confirm = safe_input("\033[1;31m[!] WARNING: This will purge all Roblox installations, installers (.exe), downloads, caches, logs & registry entries. Proceed? (y/n): \033[0m").strip().lower()
            if confirm == 'y':
                print("\n")
                deep_clean_roblox()
            else:
                print("\033[1;33m[*] Operation cancelled.\033[0m\n")
            safe_input("\033[90mPress ENTER to continue...\033[0m")
            os.system("cls" if os.name == "nt" else "clear")
            print("\n")
            print_rainbow_banner()
            print("\n" + "\033[90m" + "-"*70 + "\033[0m\n")
        else:
            print("\033[1;31m[-] Invalid choice. Please enter '1', '2' or 'q'.\033[0m\n")

if __name__ == "__main__":
    main()
