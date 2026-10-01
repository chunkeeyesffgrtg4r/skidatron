"""
Roblox 3D Avatar Viewer - Working Version
Fetches real Roblox avatar data + real 3D mesh (obj/mtl/textures)
"""

from flask import Flask, render_template_string, jsonify, Response
import threading
import webview
import socket
import time
import requests
import os
import json
import sys

app = Flask(__name__)

# Since March 23, 2026, Roblox requires auth on the -3d thumbnail endpoints.
# Create a free key at https://create.roblox.com/dashboard/credentials
# (permission: Thumbnails -> read), then either:
#   1. Put it in a file called apikey.txt (same folder as this script), or
#   2. Set it as an env var: ROBLOX_API_KEY
def load_api_key():
    key_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'apikey.txt')
    if os.path.exists(key_file):
        with open(key_file, 'r', encoding='utf-8') as f:
            key = f.read().strip()
            if key:
                return key
    return os.environ.get('ROBLOX_API_KEY', '')

ROBLOX_API_KEY = load_api_key()

WINDOW_SIZE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'window_size.json')
# Sidebar mode: smaller, compact sidebar
DEFAULT_WINDOW_SIZE = {'width': 300, 'height': 600}


def load_window_size():
    if os.path.exists(WINDOW_SIZE_FILE):
        try:
            with open(WINDOW_SIZE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {
                    'width': int(data.get('width', DEFAULT_WINDOW_SIZE['width'])),
                    'height': int(data.get('height', DEFAULT_WINDOW_SIZE['height']))
                }
        except Exception as e:
            print(f"⚠️ Could not read saved window size, using default: {e}")
    return dict(DEFAULT_WINDOW_SIZE)


def save_window_size(size):
    try:
        with open(WINDOW_SIZE_FILE, 'w', encoding='utf-8') as f:
            json.dump(size, f)
    except Exception as e:
        print(f"⚠️ Could not save window size: {e}")

WINDOW_POSITION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'window_position.json')


def load_window_position():
    """Returns {'x': int, 'y': int} if a position was saved, else None (let the
    OS/webview pick a default spot for the very first launch)."""
    if os.path.exists(WINDOW_POSITION_FILE):
        try:
            with open(WINDOW_POSITION_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return {'x': int(data['x']), 'y': int(data['y'])}
        except Exception as e:
            print(f"⚠️ Could not read saved window position: {e}")
    return None


def save_window_position(pos):
    try:
        with open(WINDOW_POSITION_FILE, 'w', encoding='utf-8') as f:
            json.dump(pos, f)
    except Exception as e:
        print(f"⚠️ Could not save window position: {e}")


LAST_PROFILE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'last_profile.json')


def load_last_profile():
    if os.path.exists(LAST_PROFILE_FILE):
        try:
            with open(LAST_PROFILE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                query = str(data.get('query', '')).strip()
                if query:
                    return query
        except Exception as e:
            print(f"⚠️ Could not read last profile, using default: {e}")
    return '1'


def save_last_profile(query):
    try:
        with open(LAST_PROFILE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'query': query}, f)
    except Exception as e:
        print(f"⚠️ Could not save last profile: {e}")

SIDEBAR_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sidebar_state.json')


def load_sidebar_collapsed():
    if os.path.exists(SIDEBAR_STATE_FILE):
        try:
            with open(SIDEBAR_STATE_FILE, 'r', encoding='utf-8') as f:
                return bool(json.load(f).get('collapsed', False))
        except Exception as e:
            print(f"⚠️ Could not read sidebar state, using default: {e}")
    return False


def save_sidebar_collapsed(collapsed):
    try:
        with open(SIDEBAR_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump({'collapsed': bool(collapsed)}, f)
    except Exception as e:
        print(f"⚠️ Could not save sidebar state: {e}")

UI_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui_settings.json')
DEFAULT_UI_SETTINGS = {
    'espBox': True, 'espCornerBox': False, 'espFill': False,
    'espHealth': True, 'espName': True, 'espDistance': True,
    'autoRotate': True, 'skeleton': False
}


def load_ui_settings():
    settings = dict(DEFAULT_UI_SETTINGS)
    if os.path.exists(UI_SETTINGS_FILE):
        try:
            with open(UI_SETTINGS_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                for key in DEFAULT_UI_SETTINGS:
                    if key in saved:
                        settings[key] = bool(saved[key])
        except Exception as e:
            print(f"⚠️ Could not read UI settings, using defaults: {e}")
    return settings


def save_ui_settings(partial):
    settings = load_ui_settings()
    for key in DEFAULT_UI_SETTINGS:
        if key in partial:
            settings[key] = bool(partial[key])
    try:
        with open(UI_SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f)
    except Exception as e:
        print(f"⚠️ Could not save UI settings: {e}")

CAMERA_VIEW_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'camera_view.json')


def load_camera_view():
    """The viewing angle around the model (azimuth/polar/distance-ratio), not the
    avatar's own pose -- Roblox's exported mesh has no adjustable rig/facing."""
    if os.path.exists(CAMERA_VIEW_FILE):
        try:
            with open(CAMERA_VIEW_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if all(k in data for k in ('azimuthal', 'polar', 'distanceRatio')):
                    return data
        except Exception as e:
            print(f"⚠️ Could not read saved camera view: {e}")
    return None


def save_camera_view(view):
    try:
        with open(CAMERA_VIEW_FILE, 'w', encoding='utf-8') as f:
            json.dump({
                'azimuthal': float(view.get('azimuthal', 0)),
                'polar': float(view.get('polar', 0)),
                'distanceRatio': float(view.get('distanceRatio', 1.8))
            }, f)
    except Exception as e:
        print(f"⚠️ Could not save camera view: {e}")






PAGE_HTML = '<!DOCTYPE html>\n<html lang="en">\n<head>\n    <meta charset="UTF-8">\n    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n    <title>Roblox 3D Avatar Viewer</title>\n    <style>\n        * { margin: 0; padding: 0; box-sizing: border-box; }\n\n        body {\n            font-family: Arial, sans-serif;\n            background: #1a1a1a;\n            height: 100vh;\n            display: flex;\n            justify-content: stretch;\n            align-items: stretch;\n            padding: 0;\n            overflow: hidden;\n        }\n\n        .container {\n            display: flex;\n            gap: 0;\n            width: 100%;\n            height: 100%;\n            background: #1a1a1a;\n            border-radius: 0;\n            box-shadow: none;\n            overflow: hidden;\n            transition: none;\n        }\n\n        .sidebar {\n            width: 0;\n            flex-shrink: 0;\n            padding: 0;\n            overflow-y: auto;\n            transition: width 0.15s ease, padding 0.15s ease, opacity 0.15s ease;\n            background: #0d0d0d;\n            display: none;\n            flex-direction: column;\n            gap: 15px;\n        }\n\n        h1 { color: #667eea; font-size: 20px; text-align: center; }\n        p { text-align: center; color: #aaa; font-size: 12px; }\n        label { font-weight: bold; color: #ddd; font-size: 12px; }\n\n        input, button {\n            padding: 10px;\n            border: 1px solid #555;\n            border-radius: 5px;\n            font-size: 14px;\n            width: 100%;\n            background: #222;\n            color: #ddd;\n        }\n\n        input { margin-bottom: 5px; }\n\n        button {\n            background: #667eea;\n            color: white;\n            border: none;\n            cursor: pointer;\n            font-weight: bold;\n            margin-bottom: 5px;\n        }\n\n        button:hover { background: #764ba2; }\n        button:disabled { background: #aaa; cursor: not-allowed; }\n\n        .status {\n            background: #222;\n            padding: 15px;\n            border-radius: 5px;\n            border: 1px solid #444;\n            font-size: 13px;\n        }\n\n        .status-label { font-weight: bold; color: #667eea; font-size: 11px; margin-bottom: 5px; }\n        .status-text { color: #ccc; font-size: 12px; word-break: break-word; }\n        .status-text.success { color: #27ae60; }\n        .status-text.error { color: #e74c3c; }\n        .status-text.loading { color: #667eea; animation: pulse 1s infinite; }\n\n        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.6; } }\n\n        .thumb-row { display: flex; align-items: center; gap: 10px; }\n        .thumb-row img { width: 48px; height: 48px; border-radius: 6px; object-fit: cover; background: #ddd; }\n\n        .online-row { display: flex; align-items: center; gap: 6px; margin-top: 2px; }\n        .online-dot { width: 8px; height: 8px; border-radius: 50%; background: #aaa; flex-shrink: 0; }\n        .online-dot.online { background: #2ecc71; }\n        .online-dot.offline { background: #999; }\n        .online-label.online { color: #27ae60; }\n        .online-label.offline { color: #888; }\n\n        .viewer {\n            flex: 1;\n            background: #1a1a1a;\n            position: relative;\n            min-height: 0;\n            min-width: 0;\n            display: flex;\n            align-items: center;\n            justify-content: center;\n            overflow: hidden;\n        }\n\n        .sidebar.collapsed {\n            width: 0;\n            padding-left: 0;\n            padding-right: 0;\n            opacity: 0;\n            overflow: hidden;\n        }\n\n        #sidebarToggleBtn {\n            position: absolute;\n            top: 10px;\n            left: 10px;\n            width: 34px;\n            height: 34px;\n            padding: 0;\n            border-radius: 50%;\n            background: rgba(0,0,0,0.55);\n            border: 1px solid rgba(255,255,255,0.25);\n            color: #fff;\n            font-size: 16px;\n            line-height: 1;\n            cursor: pointer;\n            z-index: 11;\n            margin: 0;\n        }\n        #sidebarToggleBtn:hover { background: rgba(0,0,0,0.75); }\n\n        #fullscreenToggleBtn {\n            position: absolute;\n            top: 10px;\n            left: 54px;\n            width: 34px;\n            height: 34px;\n            padding: 0;\n            border-radius: 50%;\n            background: rgba(0,0,0,0.55);\n            border: 1px solid rgba(255,255,255,0.25);\n            color: #fff;\n            font-size: 16px;\n            line-height: 1;\n            cursor: pointer;\n            z-index: 11;\n            margin: 0;\n        }\n        #fullscreenToggleBtn:hover { background: rgba(0,0,0,0.75); }\n\n        .viewer canvas { display: block; width: 100%; height: 100%; min-width: 150px; min-height: 150px; }\n\n        .viewer-overlay {\n            position: absolute;\n            top: 0; left: 0; right: 0; bottom: 0;\n            display: flex;\n            justify-content: center;\n            align-items: center;\n            color: #888;\n            font-size: 14px;\n            pointer-events: none;\n            text-align: center;\n        }\n\n        .quick-load { display: flex; gap: 5px; }\n        .quick-load button { flex: 1; margin: 0; padding: 8px; font-size: 12px; }\n\n        .toggle-row { display: flex; gap: 5px; }\n        .toggle-row button { flex: 1; margin: 0; padding: 8px; font-size: 11px; }\n\n        /* --- ESP-style HUD overlay (decorative viewer overlay only) --- */\n        #espHud {\n            position: absolute;\n            inset: 0;\n            pointer-events: none;\n            overflow: visible;\n        }\n\n        .esp-box {\n            position: absolute;\n            border: 2px solid #00eaff;\n            box-shadow: 0 0 4px rgba(0, 234, 255, 0.6);\n            display: none;\n        }\n\n        .esp-fill {\n            position: absolute;\n            background: rgba(0, 234, 255, 0.12);\n            display: none;\n        }\n\n        #espCornerBox { position: absolute; display: none; }\n        .esp-corner { position: absolute; }\n        .corner-tl { border-top: 3px solid #ffb300; border-left: 3px solid #ffb300; }\n        .corner-tr { border-top: 3px solid #ffb300; border-right: 3px solid #ffb300; }\n        .corner-bl { border-bottom: 3px solid #ffb300; border-left: 3px solid #ffb300; }\n        .corner-br { border-bottom: 3px solid #ffb300; border-right: 3px solid #ffb300; }\n\n        .esp-name {\n            position: absolute;\n            transform: translate(-50%, -100%);\n            color: #fff;\n            font-size: 13px;\n            font-weight: bold;\n            text-shadow: 0 0 3px #000, 0 0 3px #000, 1px 1px 1px #000;\n            white-space: nowrap;\n            display: none;\n        }\n\n        .esp-distance {\n            position: absolute;\n            transform: translate(-50%, 0);\n            color: #e0e0e0;\n            font-size: 11px;\n            text-shadow: 0 0 3px #000, 1px 1px 1px #000;\n            white-space: nowrap;\n            display: none;\n        }\n\n        #espHealthOuter {\n            position: absolute;\n            width: 6px;\n            background: rgba(0, 0, 0, 0.55);\n            border: 1px solid rgba(255, 255, 255, 0.3);\n            display: none;\n        }\n        #espHealthFill {\n            position: absolute;\n            left: 0; right: 0; bottom: 0;\n            height: 100%;\n            background: #2ecc71;\n        }\n\n        #espGearBtn {\n            position: absolute;\n            top: 10px;\n            right: 10px;\n            width: 34px;\n            height: 34px;\n            padding: 0;\n            border-radius: 50%;\n            background: rgba(0,0,0,0.55);\n            border: 1px solid rgba(255,255,255,0.25);\n            color: #fff;\n            font-size: 16px;\n            line-height: 1;\n            cursor: pointer;\n            z-index: 10;\n            margin: 0;\n        }\n        #espGearBtn:hover { background: rgba(0,0,0,0.75); }\n\n        #espPanel {\n            position: absolute;\n            top: 50px;\n            right: 10px;\n            width: 175px;\n            background: rgba(20, 20, 20, 0.92);\n            border: 1px solid rgba(255,255,255,0.2);\n            border-radius: 8px;\n            padding: 10px;\n            display: none;\n            z-index: 10;\n            color: #eee;\n            font-size: 12px;\n        }\n        #espPanel label {\n            display: flex;\n            align-items: center;\n            gap: 6px;\n            color: #eee;\n            font-weight: normal;\n            font-size: 12px;\n            margin: 6px 0;\n            cursor: pointer;\n        }\n        #espPanel input[type="checkbox"] { width: auto; margin: 0; }\n        #espPanel .esp-panel-title {\n            font-weight: bold;\n            font-size: 12px;\n            color: #00eaff;\n            margin-bottom: 4px;\n        }\n        #espPanel .esp-hint {\n            font-size: 10px;\n            color: #999;\n            margin-top: 6px;\n            line-height: 1.4;\n        }\n\n        @media (max-width: 800px) {\n            .container { flex-direction: column; }\n            .sidebar { width: 100%; }\n            .viewer { min-height: 320px; }\n        }\n    </style>\n</head>\n<body>\n    <div class="container">\n        <div class="sidebar{% if sidebar_collapsed %} collapsed{% endif %}">\n            <h1>🎨 3D Avatar Viewer</h1>\n            <p>Real Roblox Avatars in 3D</p>\n\n            <div>\n                <label>Enter Roblox User ID</label>\n                <input type="text" id="userId" value="{{ last_profile }}" placeholder="User ID or Username">\n                <button onclick="loadAvatar()">🔍 Load Avatar</button>\n            </div>\n\n            <div class="quick-load">\n                <button onclick="loadUser(1)" style="font-size: 11px;">User #1</button>\n                <button onclick="loadUser(3)" style="font-size: 11px;">User #3</button>\n                <button onclick="loadUser(156)" style="font-size: 11px;">User #156</button>\n            </div>\n\n            <div class="toggle-row">\n                <button id="autoRotateBtn" onclick="toggleAutoRotate()">🔄 Auto-Rotate: {% if ui.autoRotate %}On{% else %}Off{% endif %}</button>\n            </div>\n\n            <div class="toggle-row">\n                <button id="skeletonBtn" onclick="toggleSkeleton()">🦴 Skeleton: {% if ui.skeleton %}On{% else %}Off{% endif %}</button>\n            </div>\n\n            <div class="toggle-row">\n                <button id="steamProofBtn" onclick="toggleSteamProof()">🔒 Steam Proof: Off</button>\n            </div>\n\n            <div class="status">\n                <div class="status-label">📊 STATUS</div>\n                <div class="status-text" id="status">Ready</div>\n            </div>\n\n            <div class="status">\n                <div class="status-label">ℹ️ INFO</div>\n                <div class="thumb-row">\n                    <img id="thumbImg" src="" style="display:none;">\n                    <div>\n                        <div class="status-text" id="username">-</div>\n                        <div class="online-row">\n                            <span class="online-dot" id="onlineDot"></span>\n                            <span class="status-text online-label" id="onlineLabel"></span>\n                        </div>\n                        <div class="status-text" id="userIdText" style="color:#888;"></div>\n                    </div>\n                </div>\n            </div>\n        </div>\n\n        <div class="viewer" id="viewer">\n            <div class="viewer-overlay" id="viewerOverlay">Enter a user ID and click Load Avatar</div>\n\n            <button id="sidebarToggleBtn" title="Hide sidebar (just show the 3D model)">&#9776;</button>\n\n            <button id="fullscreenToggleBtn" title="Hide the top bar (fullscreen)">&#9974;</button>\n\n            <button id="espGearBtn" title="Overlay settings">⚙️</button>\n            <div id="espPanel">\n                <div class="esp-panel-title">Overlay Settings</div>\n                <label><input type="checkbox" id="espChkBox" {% if ui.espBox %}checked{% endif %} onchange="espToggle(\'box\', this.checked)"> Box</label>\n                <label><input type="checkbox" id="espChkCornerBox" {% if ui.espCornerBox %}checked{% endif %} onchange="espToggle(\'cornerBox\', this.checked)"> Corner Box</label>\n                <label><input type="checkbox" id="espChkFill" {% if ui.espFill %}checked{% endif %} onchange="espToggle(\'fill\', this.checked)"> Box Fill</label>\n                <label><input type="checkbox" id="espChkHealth" {% if ui.espHealth %}checked{% endif %} onchange="espToggle(\'health\', this.checked)"> Health Bar</label>\n                <label><input type="checkbox" id="espChkName" {% if ui.espName %}checked{% endif %} onchange="espToggle(\'name\', this.checked)"> Name Tag</label>\n                <label><input type="checkbox" id="espChkDistance" {% if ui.espDistance %}checked{% endif %} onchange="espToggle(\'distance\', this.checked)"> Distance</label>\n                <div class="esp-hint">Box &amp; Corner Box can\'t both be on — picking one turns the other off. Everything else stacks freely.</div>\n            </div>\n\n            <div id="espHud">\n                <div class="esp-fill" id="espFill"></div>\n                <div class="esp-box" id="espBox"></div>\n                <div id="espCornerBox">\n                    <div class="esp-corner corner-tl" id="espCornerTL"></div>\n                    <div class="esp-corner corner-tr" id="espCornerTR"></div>\n                    <div class="esp-corner corner-bl" id="espCornerBL"></div>\n                    <div class="esp-corner corner-br" id="espCornerBR"></div>\n                </div>\n                <div id="espHealthOuter"><div id="espHealthFill"></div></div>\n                <div class="esp-name" id="espName">Player</div>\n                <div class="esp-distance" id="espDistance">67m</div>\n            </div>\n        </div>\n    </div>\n\n    <script type="importmap">\n    {\n        "imports": {\n            "three": "https://unpkg.com/three@0.160.0/build/three.module.js",\n            "three/addons/": "https://unpkg.com/three@0.160.0/examples/jsm/"\n        }\n    }\n    </script>\n\n    <script type="module">\n        import * as THREE from \'three\';\n        import { OrbitControls } from \'three/addons/controls/OrbitControls.js\';\n        import { OBJLoader } from \'three/addons/loaders/OBJLoader.js\';\n        import { MTLLoader } from \'three/addons/loaders/MTLLoader.js\';\n\n        const viewerEl = document.getElementById(\'viewer\');\n        const overlayEl = document.getElementById(\'viewerOverlay\');\n\n        let scene, camera, renderer, controls, currentModel;\n        let autoRotate = document.getElementById(\'autoRotateBtn\').textContent.trim().endsWith(\'On\');\n        let skeletonGroup = null;\n        let skeletonVisible = document.getElementById(\'skeletonBtn\').textContent.trim().endsWith(\'On\');\n        let lastModelSize = null;\n        const savedCameraView = {{ camera_view | tojson }};\n        let saveCameraViewTimeout = null;\n\n        // --- ESP-style HUD overlay state (decorative only, no real game data) ---\n        let currentAvatarName = \'Player\';\n        const espSettings = {\n            box: document.getElementById(\'espChkBox\').checked,\n            cornerBox: document.getElementById(\'espChkCornerBox\').checked,\n            fill: document.getElementById(\'espChkFill\').checked,\n            health: document.getElementById(\'espChkHealth\').checked,\n            name: document.getElementById(\'espChkName\').checked,\n            distance: document.getElementById(\'espChkDistance\').checked\n        };\n\n        let lastLocalUiChangeAt = 0;\n        function saveUiSettings() {\n            lastLocalUiChangeAt = Date.now();\n            fetch(\'/api/ui-settings\', {\n                method: \'POST\',\n                headers: { \'Content-Type\': \'application/json\' },\n                body: JSON.stringify({\n                    espBox: espSettings.box,\n                    espCornerBox: espSettings.cornerBox,\n                    espFill: espSettings.fill,\n                    espHealth: espSettings.health,\n                    espName: espSettings.name,\n                    espDistance: espSettings.distance,\n                    autoRotate: autoRotate,\n                    skeleton: skeletonVisible\n                })\n            }).catch(() => {});\n        }\n\n        window.espToggle = function(key, checked) {\n            espSettings[key] = checked;\n            if (checked && key === \'box\') {\n                espSettings.cornerBox = false;\n                const cb = document.getElementById(\'espChkCornerBox\');\n                if (cb) cb.checked = false;\n            }\n            if (checked && key === \'cornerBox\') {\n                espSettings.box = false;\n                const cb = document.getElementById(\'espChkBox\');\n                if (cb) cb.checked = false;\n            }\n            saveUiSettings();\n        };\n\n        window.setEspName = function(name) {\n            currentAvatarName = name || \'Player\';\n        };\n\n        let steamProofEnabled = false;\n        window.toggleSteamProof = function() {\n            steamProofEnabled = !steamProofEnabled;\n            const btn = document.getElementById(\'steamProofBtn\');\n            if (btn) btn.textContent = \'🔒 Steam Proof: \' + (steamProofEnabled ? \'On\' : \'Off\');\n            \n            fetch(\'/api/toggle-steam-proof\', {\n                method: \'POST\',\n                headers: { \'Content-Type\': \'application/json\' },\n                body: JSON.stringify({ enabled: steamProofEnabled })\n            }).then(r => r.json()).then(d => {\n                if (!d.success) {\n                    steamProofEnabled = !steamProofEnabled;\n                    if (btn) btn.textContent = \'🔒 Steam Proof: \' + (steamProofEnabled ? \'On\' : \'Off\');\n                }\n            }).catch(e => console.warn(\'Steam Proof error:\', e));\n        };\n\n        // Poll for changes made externally (e.g. via /api/esp-signal from another script)\n        // and apply them live if this window is already open.\n        function applyIncomingSettings(s) {\n            const map = { box: \'espChkBox\', cornerBox: \'espChkCornerBox\', fill: \'espChkFill\', health: \'espChkHealth\', name: \'espChkName\', distance: \'espChkDistance\' };\n            for (const key of Object.keys(map)) {\n                const settingKey = \'esp\' + key.charAt(0).toUpperCase() + key.slice(1);\n                const desired = s[settingKey];\n                if (typeof desired === \'boolean\' && desired !== espSettings[key]) {\n                    document.getElementById(map[key]).checked = desired;\n                    window.espToggle(key, desired);\n                }\n            }\n            if (typeof s.autoRotate === \'boolean\' && s.autoRotate !== autoRotate) window.toggleAutoRotate();\n            if (typeof s.skeleton === \'boolean\' && s.skeleton !== skeletonVisible) window.toggleSkeleton();\n        }\n        setInterval(() => {\n            if (Date.now() - lastLocalUiChangeAt < 1500) return;\n            fetch(\'/api/ui-settings\').then(r => r.json()).then(applyIncomingSettings).catch(() => {});\n        }, 1000);\n\n        function initScene() {\n            scene = new THREE.Scene();\n\n            camera = new THREE.PerspectiveCamera(45, viewerEl.clientWidth / viewerEl.clientHeight, 0.1, 1000);\n            camera.position.set(0, 1.2, 5.5);\n\n            renderer = new THREE.WebGLRenderer({ antialias: true });\n            renderer.setSize(viewerEl.clientWidth, viewerEl.clientHeight);\n            renderer.setPixelRatio(window.devicePixelRatio);\n            viewerEl.appendChild(renderer.domElement);\n\n            const hemi = new THREE.HemisphereLight(0xffffff, 0x444444, 1.2);\n            scene.add(hemi);\n            const dir = new THREE.DirectionalLight(0xffffff, 1.5);\n            dir.position.set(2, 4, 3);\n            scene.add(dir);\n            const dir2 = new THREE.DirectionalLight(0xffffff, 0.6);\n            dir2.position.set(-3, 2, -2);\n            scene.add(dir2);\n\n            controls = new OrbitControls(camera, renderer.domElement);\n            controls.enableDamping = true;\n            controls.autoRotate = autoRotate;\n            controls.autoRotateSpeed = 2.0;\n            controls.target.set(0, 1, 0);\n\n            controls.addEventListener(\'end\', () => {\n                clearTimeout(saveCameraViewTimeout);\n                saveCameraViewTimeout = setTimeout(saveCameraView, 400);\n            });\n\n            const gearBtn = document.getElementById(\'espGearBtn\');\n            if (gearBtn) {\n                gearBtn.addEventListener(\'click\', () => {\n                    const panel = document.getElementById(\'espPanel\');\n                    panel.style.display = panel.style.display === \'block\' ? \'none\' : \'block\';\n                });\n            }\n\n            window.addEventListener(\'resize\', onResize);\n            animate();\n        }\n\n        function onResize() {\n            if (!renderer) return;\n            camera.aspect = viewerEl.clientWidth / viewerEl.clientHeight;\n            camera.updateProjectionMatrix();\n            renderer.setSize(viewerEl.clientWidth, viewerEl.clientHeight);\n        }\n\n        // Projects the model\'s world-space bounding box corners to screen\n        // pixels and returns the 2D rect that encloses all of them -- this\n        // keeps the HUD box correctly sized/positioned as the camera orbits.\n        function getEspScreenRect(object) {\n            const box = new THREE.Box3().setFromObject(object);\n            const rectBounds = viewerEl.getBoundingClientRect();\n            let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;\n            let anyVisible = false;\n            for (let xi = 0; xi < 2; xi++) {\n                for (let yi = 0; yi < 2; yi++) {\n                    for (let zi = 0; zi < 2; zi++) {\n                        const corner = new THREE.Vector3(\n                            xi ? box.max.x : box.min.x,\n                            yi ? box.max.y : box.min.y,\n                            zi ? box.max.z : box.min.z\n                        ).project(camera);\n                        if (corner.z > 1) continue; // behind camera\n                        anyVisible = true;\n                        const sx = (corner.x * 0.5 + 0.5) * rectBounds.width;\n                        const sy = (-corner.y * 0.5 + 0.5) * rectBounds.height;\n                        minX = Math.min(minX, sx); maxX = Math.max(maxX, sx);\n                        minY = Math.min(minY, sy); maxY = Math.max(maxY, sy);\n                    }\n                }\n            }\n            if (!anyVisible) return null;\n            return { left: minX, top: minY, width: maxX - minX, height: maxY - minY };\n        }\n\n        function positionEspCorners(rect) {\n            const cornerLen = Math.max(10, Math.min(rect.width, rect.height) * 0.28);\n            const spots = {\n                espCornerTL: { left: rect.left, top: rect.top },\n                espCornerTR: { left: rect.left + rect.width - cornerLen, top: rect.top },\n                espCornerBL: { left: rect.left, top: rect.top + rect.height - cornerLen },\n                espCornerBR: { left: rect.left + rect.width - cornerLen, top: rect.top + rect.height - cornerLen }\n            };\n            Object.entries(spots).forEach(([id, pos]) => {\n                const el = document.getElementById(id);\n                el.style.left = pos.left + \'px\';\n                el.style.top = pos.top + \'px\';\n                el.style.width = cornerLen + \'px\';\n                el.style.height = cornerLen + \'px\';\n            });\n        }\n\n        function updateEspHud() {\n            const hud = document.getElementById(\'espHud\');\n            const boxEl = document.getElementById(\'espBox\');\n            const fillEl = document.getElementById(\'espFill\');\n            const cornerEl = document.getElementById(\'espCornerBox\');\n            const nameEl = document.getElementById(\'espName\');\n            const healthOuter = document.getElementById(\'espHealthOuter\');\n            const distEl = document.getElementById(\'espDistance\');\n\n            const anyOn = espSettings.box || espSettings.cornerBox || espSettings.health || espSettings.name || espSettings.distance;\n            if (!currentModel || !anyOn) {\n                boxEl.style.display = \'none\';\n                fillEl.style.display = \'none\';\n                cornerEl.style.display = \'none\';\n                nameEl.style.display = \'none\';\n                healthOuter.style.display = \'none\';\n                distEl.style.display = \'none\';\n                return;\n            }\n\n            const rect = getEspScreenRect(currentModel);\n            if (!rect) return;\n\n            const showFill = espSettings.fill && (espSettings.box || espSettings.cornerBox);\n\n            boxEl.style.display = espSettings.box ? \'block\' : \'none\';\n            if (espSettings.box) {\n                boxEl.style.left = rect.left + \'px\';\n                boxEl.style.top = rect.top + \'px\';\n                boxEl.style.width = rect.width + \'px\';\n                boxEl.style.height = rect.height + \'px\';\n            }\n\n            fillEl.style.display = showFill ? \'block\' : \'none\';\n            if (showFill) {\n                fillEl.style.left = rect.left + \'px\';\n                fillEl.style.top = rect.top + \'px\';\n                fillEl.style.width = rect.width + \'px\';\n                fillEl.style.height = rect.height + \'px\';\n            }\n\n            cornerEl.style.display = espSettings.cornerBox ? \'block\' : \'none\';\n            if (espSettings.cornerBox) positionEspCorners(rect);\n\n            nameEl.style.display = espSettings.name ? \'block\' : \'none\';\n            if (espSettings.name) {\n                nameEl.textContent = currentAvatarName;\n                nameEl.style.left = (rect.left + rect.width / 2) + \'px\';\n                nameEl.style.top = (rect.top - 6) + \'px\';\n            }\n\n            healthOuter.style.display = espSettings.health ? \'block\' : \'none\';\n            if (espSettings.health) {\n                healthOuter.style.left = (rect.left - 12) + \'px\';\n                healthOuter.style.top = rect.top + \'px\';\n                healthOuter.style.height = rect.height + \'px\';\n            }\n\n            distEl.style.display = espSettings.distance ? \'block\' : \'none\';\n            if (espSettings.distance) {\n                distEl.textContent = \'67m\';\n                distEl.style.left = (rect.left + rect.width / 2) + \'px\';\n                distEl.style.top = (rect.top + rect.height + 4) + \'px\';\n            }\n        }\n\n        function animate() {\n            requestAnimationFrame(animate);\n            controls.update();\n            updateEspHud();\n            renderer.render(scene, camera);\n        }\n\n        function clearModel() {\n            if (currentModel) {\n                scene.remove(currentModel);\n                currentModel = null;\n            }\n        }\n\n        // --- Stick-figure "skeleton" overlay ---------------------------------\n        // The OBJ avatar has no real bone/rig data, but Roblox names each\n        // mesh piece after the body part it is ("Head", "Torso"/"UpperTorso",\n        // "Left Arm"/"LeftUpperArm", etc). Instead of guessing joint spots as\n        // a fraction of overall height, read the actual bounding box of each\n        // named part and place joints there -- that\'s what keeps the lines\n        // sitting on the real limbs for both R6 and R15 avatars. Renders with\n        // depthTest off so it shows through the body like an X-ray.\n\n        function boneMesh(start, end, radius) {\n            const dir = new THREE.Vector3().subVectors(end, start);\n            const length = dir.length() || 0.0001;\n            const geometry = new THREE.CylinderGeometry(radius, radius, length, 8);\n            const material = new THREE.MeshBasicMaterial({\n                color: 0xf5f0e0,\n                transparent: true,\n                opacity: 0.95,\n                depthTest: false\n            });\n            const mesh = new THREE.Mesh(geometry, material);\n            mesh.position.copy(start).add(end).multiplyScalar(0.5);\n            mesh.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), dir.clone().normalize());\n            mesh.renderOrder = 999;\n            return mesh;\n        }\n\n        function jointMesh(pos, radius, color = 0xfff8e0) {\n            const geometry = new THREE.SphereGeometry(radius, 10, 10);\n            const material = new THREE.MeshBasicMaterial({\n                color, transparent: true, opacity: 0.95, depthTest: false\n            });\n            const mesh = new THREE.Mesh(geometry, material);\n            mesh.position.copy(pos);\n            mesh.renderOrder = 999;\n            return mesh;\n        }\n\n        function collectPartBoxes(root) {\n            const boxes = {};\n            const allNames = [];\n            root.traverse(child => {\n                if (child === root || !child.name) return;\n                allNames.push(child.name);\n                const key = child.name.trim().toLowerCase().replace(/[\\s_-]/g, \'\');\n                if (!key) return;\n                const box = new THREE.Box3().setFromObject(child);\n                if (!box.isEmpty() && !boxes[key]) boxes[key] = box;\n            });\n            console.log(\'[skeleton] named objects in loaded model:\', allNames.length ? allNames : \'(none -- single unnamed/merged mesh)\');\n            return boxes;\n        }\n\n        function partBox(boxes, names) {\n            for (const n of names) {\n                const key = n.toLowerCase().replace(/[\\s_-]/g, \'\');\n                if (boxes[key]) return boxes[key];\n            }\n            return null;\n        }\n\n        const topCenter = box => { const c = box.getCenter(new THREE.Vector3()); return new THREE.Vector3(c.x, box.max.y, c.z); };\n        const bottomCenter = box => { const c = box.getCenter(new THREE.Vector3()); return new THREE.Vector3(c.x, box.min.y, c.z); };\n        const midCenter = box => box.getCenter(new THREE.Vector3());\n\n        // Builds one side (left/right) of an arm or leg from whichever named\n        // parts actually exist: separate Upper/Lower R15 parts (with a real\n        // elbow/knee bend) or a single R6 block (straight line only).\n        function buildLimb(boxes, side, kind, upperJoint) {\n            const bones = [], joints = {};\n            const capital = kind === \'arm\' ? \'Arm\' : \'Leg\';\n            const upper = partBox(boxes, [`${side}Upper${capital}`]);\n            const lower = partBox(boxes, [`${side}Lower${capital}`]);\n            const end = partBox(boxes, kind === \'arm\' ? [`${side}Hand`] : [`${side}Foot`]);\n            const whole = partBox(boxes, [`${side} ${capital}`, `${side}${capital}`]);\n\n            const midName = kind === \'arm\' ? \'Elbow\' : \'Knee\';\n            const endName = kind === \'arm\' ? \'Wrist\' : \'Ankle\';\n            const j1 = side + midName, j2 = side + endName;\n\n            if (upper) {\n                joints[j1] = bottomCenter(upper);\n                bones.push([upperJoint, j1]);\n                if (lower) {\n                    joints[j2] = end ? midCenter(end) : bottomCenter(lower);\n                    bones.push([j1, j2]);\n                } else if (end) {\n                    joints[j2] = midCenter(end);\n                    bones.push([j1, j2]);\n                }\n            } else if (whole) {\n                joints[j2] = bottomCenter(whole);\n                bones.push([upperJoint, j2]);\n            }\n            return { bones, joints };\n        }\n\n        function assembleSkeletonGroup(object, joints, bones) {\n            const overallSize = new THREE.Box3().setFromObject(object).getSize(new THREE.Vector3());\n            const radius = Math.max(overallSize.x, overallSize.z) * 0.009;\n            const group = new THREE.Group();\n            bones.forEach(([a, b]) => joints[a] && joints[b] && group.add(boneMesh(joints[a], joints[b], radius)));\n            Object.entries(joints).forEach(([name, pos]) => {\n                group.add(jointMesh(pos, name === \'head\' ? radius * 2.4 : radius * 1.3));\n            });\n            return group;\n        }\n\n        // Strategy A: parts with literal Roblox names (Head, Torso/UpperTorso,\n        // LeftUpperArm, etc). Works when the export keeps real part names.\n        function buildFromLiteralNames(boxes) {\n            const head = partBox(boxes, [\'Head\']);\n            const upperTorso = partBox(boxes, [\'UpperTorso\', \'Torso\']);\n            const lowerTorso = partBox(boxes, [\'LowerTorso\']);\n            if (!head || !upperTorso) return null;\n\n            const joints = {\n                head: midCenter(head),\n                neck: bottomCenter(head),\n                hip: lowerTorso ? bottomCenter(lowerTorso) : bottomCenter(upperTorso)\n            };\n            const bones = [[\'neck\', \'head\'], [\'neck\', \'hip\']];\n\n            const lShoulder = topCenter(partBox(boxes, [\'LeftUpperArm\', \'Left Arm\', \'LeftArm\']) || upperTorso);\n            const rShoulder = topCenter(partBox(boxes, [\'RightUpperArm\', \'Right Arm\', \'RightArm\']) || upperTorso);\n            joints.lShoulder = lShoulder;\n            joints.rShoulder = rShoulder;\n            bones.push([\'neck\', \'lShoulder\'], [\'neck\', \'rShoulder\']);\n\n            const lArm = buildLimb(boxes, \'Left\', \'arm\', \'lShoulder\');\n            const rArm = buildLimb(boxes, \'Right\', \'arm\', \'rShoulder\');\n            const lLeg = buildLimb(boxes, \'Left\', \'leg\', \'hip\');\n            const rLeg = buildLimb(boxes, \'Right\', \'leg\', \'hip\');\n            [lArm, rArm, lLeg, rLeg].forEach(({ bones: b, joints: j }) => {\n                bones.push(...b);\n                Object.assign(joints, j);\n            });\n            return { joints, bones };\n        }\n\n        // Strategy B: Roblox\'s avatar-3d export often anonymizes R15 part\n        // names into generic "Player1".."Player15" (still exactly 15 -- one\n        // per R15 body part). We can\'t match them by name, but we CAN tell\n        // them apart by where they actually sit: the 3 closest to the\n        // vertical centerline are head/upper-torso/lower-torso (top to\n        // bottom); of the remaining 12, the 6 on each side split into the\n        // higher 3 (upper arm/lower arm/hand) and lower 3 (upper leg/lower\n        // leg/foot).\n        function buildFromGeometricR15(boxes) {\n            const entries = Object.keys(boxes)\n                .filter(k => /^player\\d+$/.test(k))\n                .map(k => {\n                    const box = boxes[k];\n                    const c = box.getCenter(new THREE.Vector3());\n                    return { box, cx: c.x, cy: c.y };\n                });\n            if (entries.length !== 15) return null;\n\n            entries.sort((a, b) => Math.abs(a.cx) - Math.abs(b.cx));\n            const center = entries.slice(0, 3).sort((a, b) => b.cy - a.cy);\n            const sides = entries.slice(3);\n            const left = sides.filter(e => e.cx < 0).sort((a, b) => b.cy - a.cy);\n            const right = sides.filter(e => e.cx > 0).sort((a, b) => b.cy - a.cy);\n            if (center.length !== 3 || left.length !== 6 || right.length !== 6) return null;\n\n            const [head, upperTorso, lowerTorso] = center.map(e => e.box);\n            const [lUpperArm, lLowerArm, lHand, lUpperLeg, lLowerLeg, lFoot] = left.map(e => e.box);\n            const [rUpperArm, rLowerArm, rHand, rUpperLeg, rLowerLeg, rFoot] = right.map(e => e.box);\n\n            const joints = {\n                head: midCenter(head),\n                neck: bottomCenter(head),\n                hip: bottomCenter(lowerTorso),\n                lShoulder: topCenter(lUpperArm), rShoulder: topCenter(rUpperArm),\n                lElbow: bottomCenter(lUpperArm), rElbow: bottomCenter(rUpperArm),\n                lWrist: midCenter(lHand), rWrist: midCenter(rHand),\n                lHip: topCenter(lUpperLeg), rHip: topCenter(rUpperLeg),\n                lKnee: bottomCenter(lUpperLeg), rKnee: bottomCenter(rUpperLeg),\n                lAnkle: midCenter(lFoot), rAnkle: midCenter(rFoot)\n            };\n            const bones = [\n                [\'neck\', \'head\'], [\'neck\', \'hip\'],\n                [\'neck\', \'lShoulder\'], [\'neck\', \'rShoulder\'],\n                [\'lShoulder\', \'lElbow\'], [\'lElbow\', \'lWrist\'],\n                [\'rShoulder\', \'rElbow\'], [\'rElbow\', \'rWrist\'],\n                [\'hip\', \'lHip\'], [\'hip\', \'rHip\'],\n                [\'lHip\', \'lKnee\'], [\'lKnee\', \'lAnkle\'],\n                [\'rHip\', \'rKnee\'], [\'rKnee\', \'rAnkle\']\n            ];\n            return { joints, bones };\n        }\n\n        function buildSkeletonFromParts(object) {\n            const boxes = collectPartBoxes(object);\n            const literal = buildFromLiteralNames(boxes);\n            if (literal) {\n                console.log(\'[skeleton] using literal part names\');\n                return assembleSkeletonGroup(object, literal.joints, literal.bones);\n            }\n            const geometric = buildFromGeometricR15(boxes);\n            if (geometric) {\n                console.log(\'[skeleton] using geometric R15 classification (anonymized PlayerN parts)\');\n                return assembleSkeletonGroup(object, geometric.joints, geometric.bones);\n            }\n            return null;\n        }\n\n        // Fallback for meshes with no recognizable part names: a proportional\n        // guess based on overall height, so the button still does something.\n        function buildSkeletonProportional(size) {\n            const group = new THREE.Group();\n            const h = size.y;\n            const bottom = -h / 2;\n            const halfW = size.x / 2;\n            const y = {\n                ankle: bottom + h * 0.02, knee: bottom + h * 0.26, hip: bottom + h * 0.49,\n                shoulder: bottom + h * 0.75, neck: bottom + h * 0.79, head: bottom + h * 0.94\n            };\n            const legX = halfW * 0.28, shoulderX = halfW * 0.44;\n            const elbowY = y.shoulder - h * 0.17, wristY = y.shoulder - h * 0.33;\n            const j = {\n                head: new THREE.Vector3(0, y.head, 0), neck: new THREE.Vector3(0, y.neck, 0),\n                hip: new THREE.Vector3(0, y.hip, 0),\n                lShoulder: new THREE.Vector3(-shoulderX, y.shoulder, 0), rShoulder: new THREE.Vector3(shoulderX, y.shoulder, 0),\n                lElbow: new THREE.Vector3(-shoulderX, elbowY, 0), rElbow: new THREE.Vector3(shoulderX, elbowY, 0),\n                lWrist: new THREE.Vector3(-shoulderX, wristY, 0), rWrist: new THREE.Vector3(shoulderX, wristY, 0),\n                lHip: new THREE.Vector3(-legX, y.hip, 0), rHip: new THREE.Vector3(legX, y.hip, 0),\n                lKnee: new THREE.Vector3(-legX, y.knee, 0), rKnee: new THREE.Vector3(legX, y.knee, 0),\n                lAnkle: new THREE.Vector3(-legX, y.ankle, 0), rAnkle: new THREE.Vector3(legX, y.ankle, 0)\n            };\n            const bones = [\n                [\'neck\', \'head\'], [\'neck\', \'hip\'], [\'neck\', \'lShoulder\'], [\'neck\', \'rShoulder\'],\n                [\'lShoulder\', \'lElbow\'], [\'lElbow\', \'lWrist\'], [\'rShoulder\', \'rElbow\'], [\'rElbow\', \'rWrist\'],\n                [\'hip\', \'lHip\'], [\'hip\', \'rHip\'], [\'lHip\', \'lKnee\'], [\'lKnee\', \'lAnkle\'],\n                [\'rHip\', \'rKnee\'], [\'rKnee\', \'rAnkle\']\n            ];\n            const radius = Math.max(size.x, size.z) * 0.009;\n            bones.forEach(([a, b]) => group.add(boneMesh(j[a], j[b], radius)));\n            Object.entries(j).forEach(([name, pos]) => {\n                group.add(jointMesh(pos, name === \'head\' ? radius * 2.4 : radius * 1.3));\n            });\n            return group;\n        }\n\n        function rebuildSkeleton() {\n            if (skeletonGroup) {\n                scene.remove(skeletonGroup);\n                skeletonGroup = null;\n            }\n            if (!currentModel) return;\n            const fromParts = buildSkeletonFromParts(currentModel);\n            console.log(fromParts ? \'[skeleton] using real named body-part boxes\' : \'[skeleton] no usable named parts -- using proportional guess\');\n            skeletonGroup = fromParts || (lastModelSize ? buildSkeletonProportional(lastModelSize) : null);\n            if (!skeletonGroup) return;\n            skeletonGroup.visible = skeletonVisible;\n            scene.add(skeletonGroup);\n        }\n\n        window.toggleSkeleton = function() {\n            skeletonVisible = !skeletonVisible;\n            if (skeletonGroup) skeletonGroup.visible = skeletonVisible;\n            document.getElementById(\'skeletonBtn\').textContent =\n                `🦴 Skeleton: ${skeletonVisible ? \'On\' : \'Off\'}`;\n            saveUiSettings();\n        };\n\n        function saveCameraView() {\n            if (!lastModelSize) return;\n            const maxDim = Math.max(lastModelSize.x, lastModelSize.y, lastModelSize.z);\n            const offset = new THREE.Vector3().copy(camera.position).sub(controls.target);\n            const spherical = new THREE.Spherical().setFromVector3(offset);\n            fetch(\'/api/camera-view\', {\n                method: \'POST\',\n                headers: { \'Content-Type\': \'application/json\' },\n                body: JSON.stringify({\n                    azimuthal: spherical.theta,\n                    polar: spherical.phi,\n                    distanceRatio: spherical.radius / maxDim\n                })\n            }).catch(() => {});\n        }\n\n        function frameModel(object) {\n            const box = new THREE.Box3().setFromObject(object);\n            const size = box.getSize(new THREE.Vector3());\n            const center = box.getCenter(new THREE.Vector3());\n\n            object.position.sub(center);\n            object.updateMatrixWorld(true);\n            lastModelSize = size.clone();\n            rebuildSkeleton();\n\n            const maxDim = Math.max(size.x, size.y, size.z);\n            controls.target.set(0, 0, 0);\n            if (savedCameraView) {\n                const dist = maxDim * savedCameraView.distanceRatio;\n                const spherical = new THREE.Spherical(dist, savedCameraView.polar, savedCameraView.azimuthal);\n                camera.position.setFromSpherical(spherical).add(controls.target);\n            } else {\n                camera.position.set(0, size.y * 0.15, maxDim * 1.8);\n            }\n            controls.update();\n        }\n\n        window.loadModel3D = function(userId) {\n            overlayEl.textContent = \'Loading 3D model...\';\n            overlayEl.style.display = \'flex\';\n\n            fetch(`/api/avatar3d/${userId}`)\n                .then(r => r.json())\n                .then(async (data) => {\n                    if (data.error) throw new Error(data.error);\n\n                    // Pre-check the mtl proxy so a real backend error (auth,\n                    // CDN block, etc.) shows up instead of a vague loader failure.\n                    const mtlCheck = await fetch(data.mtlUrl);\n                    const mtlCheckText = await mtlCheck.text();\n                    if (!mtlCheck.ok) {\n                        let msg = mtlCheckText;\n                        try { msg = JSON.parse(mtlCheckText).error; } catch (e) {}\n                        throw new Error(`MTL fetch failed: ${msg}`);\n                    }\n\n                    const objCheck = await fetch(data.objUrl);\n                    const objCheckText = await objCheck.text();\n                    if (!objCheck.ok) {\n                        let msg = objCheckText;\n                        try { msg = JSON.parse(objCheckText).error; } catch (e) {}\n                        throw new Error(`OBJ fetch failed: ${msg}`);\n                    }\n\n                    const mtlLoader = new MTLLoader();\n                    mtlLoader.setResourcePath(`/api/model/${userId}/`);\n                    mtlLoader.load(data.mtlUrl, (materials) => {\n                        materials.preload();\n                        Object.values(materials.materials).forEach(mat => {\n                            mat.side = THREE.DoubleSide;\n                            // Roblox\'s MTL files often set a "d" (dissolve) value\n                            // below 1.0, which MTLLoader turns into a transparent,\n                            // partially see-through material. Force it opaque.\n                            mat.transparent = false;\n                            mat.opacity = 1;\n                            mat.alphaTest = 0;\n                            mat.depthWrite = true;\n                        });\n\n                        const objLoader = new OBJLoader();\n                        objLoader.setMaterials(materials);\n                        objLoader.load(data.objUrl, (object) => {\n                            clearModel();\n                            currentModel = object;\n                            scene.add(object);\n                            frameModel(object);\n                            overlayEl.style.display = \'none\';\n                            updateStatus(\'✅ 3D model loaded\', \'success\');\n                        }, undefined, (err) => {\n                            console.error(err);\n                            overlayEl.textContent = \'Failed to parse 3D mesh\';\n                            updateStatus(\'❌ Failed to parse 3D mesh (see console)\', \'error\');\n                        });\n                    }, undefined, (err) => {\n                        console.error(err);\n                        overlayEl.textContent = \'Failed to parse materials\';\n                        updateStatus(\'❌ Failed to parse materials (see console)\', \'error\');\n                    });\n                })\n                .catch(err => {\n                    console.error(err);\n                    overlayEl.textContent = \'3D model unavailable for this user\';\n                    updateStatus(`❌ 3D error: ${err.message}`, \'error\');\n                });\n        };\n\n        window.toggleAutoRotate = function() {\n            autoRotate = !autoRotate;\n            controls.autoRotate = autoRotate;\n            document.getElementById(\'autoRotateBtn\').textContent = `🔄 Auto-Rotate: ${autoRotate ? \'On\' : \'Off\'}`;\n            saveUiSettings();\n        };\n\n        initScene();\n    </script>\n\n    <script>\n        async function loadAvatar() {\n            const userId = document.getElementById(\'userId\').value;\n            if (!userId) {\n                updateStatus(\'❌ Please enter a user ID\', \'error\');\n                return;\n            }\n\n            updateStatus(\'⏳ Loading...\', \'loading\');\n\n            let resolvedUserId;\n            try {\n                const response = await fetch(`/api/avatar/${userId}`);\n                if (!response.ok) throw new Error(`User not found (HTTP ${response.status})`);\n                const data = await response.json();\n                resolvedUserId = data.userId;\n                displayAvatarInfo(data);\n                updateStatus(`✅ Loaded: ${data.username}`, \'success\');\n                fetch(\'/api/last-profile\', { method: \'POST\', headers: { \'Content-Type\': \'application/json\' }, body: JSON.stringify({ query: userId }) }).catch(() => {});\n            } catch (error) {\n                console.error(\'Error:\', error);\n                updateStatus(`❌ ${error.message}`, \'error\');\n                return;\n            }\n\n            window.loadModel3D(resolvedUserId);\n        }\n\n        function displayAvatarInfo(data) {\n            const thumb = document.getElementById(\'thumbImg\');\n            if (data.avatarUrl) {\n                thumb.src = data.avatarUrl;\n                thumb.style.display = \'block\';\n            } else {\n                thumb.style.display = \'none\';\n            }\n            document.getElementById(\'username\').textContent = data.username;\n            document.getElementById(\'userIdText\').textContent = `ID: ${data.userId}`;\n            if (window.setEspName) window.setEspName(data.username);\n\n            const onlineDot = document.getElementById(\'onlineDot\');\n            const onlineLabel = document.getElementById(\'onlineLabel\');\n            const presence = data.presence || \'offline\';\n            const isActive = presence === \'online\' || presence === \'in_game\' || presence === \'in_studio\';\n            const labels = {\n                online: \'Online\',\n                in_game: \'In Game\',\n                in_studio: \'In Studio\',\n                invisible: \'Offline\',\n                offline: \'Offline\'\n            };\n            onlineDot.className = \'online-dot \' + (isActive ? \'online\' : \'offline\');\n            onlineLabel.className = \'status-text online-label \' + (isActive ? \'online\' : \'offline\');\n            onlineLabel.textContent = labels[presence] || \'Offline\';\n        }\n\n        function loadUser(userId) {\n            document.getElementById(\'userId\').value = userId;\n            loadAvatar();\n        }\n\n        function updateStatus(text, type) {\n            const status = document.getElementById(\'status\');\n            status.textContent = text;\n            status.className = \'status-text \' + type;\n        }\n\n        const sidebar = document.querySelector(\'.sidebar\');\n        const sidebarToggleBtn = document.getElementById(\'sidebarToggleBtn\');\n        // Server rendered the initial collapsed/expanded state directly into the HTML,\n        // so just sync the button title to match -- no client-side toggle needed on load.\n        sidebarToggleBtn.title = sidebar.classList.contains(\'collapsed\') ? \'Show sidebar\' : \'Hide sidebar (just show the 3D model)\';\n\n        const fullscreenToggleBtn = document.getElementById(\'fullscreenToggleBtn\');\n        fullscreenToggleBtn.addEventListener(\'click\', () => {\n            if (window.pywebview && window.pywebview.api) {\n                window.pywebview.api.toggle_fullscreen();\n            }\n        });\n        sidebar.addEventListener(\'transitionend\', () => window.dispatchEvent(new Event(\'resize\')));\n        sidebarToggleBtn.addEventListener(\'click\', () => {\n            const collapsed = !sidebar.classList.contains(\'collapsed\');\n            sidebar.classList.toggle(\'collapsed\', collapsed);\n            sidebarToggleBtn.title = collapsed ? \'Show sidebar\' : \'Hide sidebar (just show the 3D model)\';\n            window.dispatchEvent(new Event(\'resize\'));\n            fetch(\'/api/sidebar-state\', { method: \'POST\', headers: { \'Content-Type\': \'application/json\' }, body: JSON.stringify({ collapsed }) }).catch(() => {});\n        });\n\n        window.addEventListener(\'load\', () => {\n            loadAvatar();\n        });\n    </script>\n</body>\n</html>\n'


# In-memory cache: user_id -> {'obj': hash, 'mtl': hash, 'textures': [hashes]}
MODEL_CACHE = {}


def resolve_cdn_url(content_hash):
    """Roblox content hashes map to one of several t0-t7.rbxcdn.com subdomains.

    Roblox now returns hashes in the "30DAY-<32-char-hash>" format (38 chars
    total) instead of the bare 32-char hash. The subdomain-selection XOR has
    to run over the *full* 38-char string -- including the "30DAY-" prefix --
    or it picks the wrong server and you get a 403. Slicing to [:38] still
    works fine on old-style bare 32-char hashes (slicing past the end of a
    string just returns the whole string), so this is backward compatible.
    """
    i = 31
    for char in content_hash[:38]:
        i ^= ord(char)
    return f"https://t{i % 8}.rbxcdn.com/{content_hash}"


class AvatarFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def fetch_avatar_thumbnail_url(self, user_id):
        """Flat 2D bust thumbnail (for the sidebar preview)."""
        try:
            url = "https://thumbnails.roblox.com/v1/users/avatar-bust"
            params = {'userIds': user_id, 'size': '420x420', 'format': 'Png', 'isCircular': 'false'}
            response = self.session.get(url, params=params, timeout=10)
            if response.status_code == 200:
                results = response.json().get('data', [])
                if results and results[0].get('state') == 'Completed':
                    return results[0].get('imageUrl')
        except Exception as e:
            print(f"Error fetching avatar thumbnail: {e}")
        return None

    # userPresenceType -> our own presence label
    PRESENCE_TYPES = {
        0: 'offline',
        1: 'online',
        2: 'in_game',
        3: 'in_studio',
        4: 'invisible',
    }

    def fetch_presence(self, user_id):
        """Real online/offline/in-game status.

        users.roblox.com's /v1/users/{id} endpoint (used in fetch_avatar_data)
        has NO isOnline field at all -- reading it always silently returned
        False. Actual presence lives on a separate endpoint, and it also
        distinguishes "in a game" / "in Studio" from just "online on the site".
        """
        try:
            url = "https://presence.roblox.com/v1/presence/users"
            headers = {'x-api-key': ROBLOX_API_KEY} if ROBLOX_API_KEY else {}
            resp = self.session.post(url, json={'userIds': [int(user_id)]}, headers=headers, timeout=10)
            if resp.status_code == 200:
                presences = resp.json().get('userPresences', [])
                if presences:
                    ptype = presences[0].get('userPresenceType', 0)
                    return self.PRESENCE_TYPES.get(ptype, 'offline')
            else:
                print(f"⚠️ Presence lookup failed (HTTP {resp.status_code}): {resp.text[:200]}")
        except Exception as e:
            print(f"Error fetching presence: {e}")
        return 'offline'

    def resolve_username_to_id(self, username):
        """Turns a Roblox username (e.g. 'CHUNKER183') into a numeric user ID."""
        try:
            url = "https://users.roblox.com/v1/usernames/users"
            resp = self.session.post(
                url,
                json={'usernames': [username], 'excludeBannedUsers': False},
                timeout=10
            )
            if resp.status_code == 200:
                results = resp.json().get('data', [])
                if results:
                    return str(results[0]['id'])
        except Exception as e:
            print(f"Error resolving username '{username}': {e}")
        return None

    def fetch_avatar_data(self, user_id):
        try:
            # If it's not purely numeric, treat it as a username and resolve first.
            if not str(user_id).isdigit():
                print(f"🔎 Resolving username: {user_id}")
                resolved_id = self.resolve_username_to_id(user_id)
                if not resolved_id:
                    print(f"❌ Username not found: {user_id}")
                    return None
                print(f"✅ Resolved '{user_id}' -> user ID {resolved_id}")
                user_id = resolved_id

            print(f"📥 Fetching avatar for user: {user_id}")
            user_url = f"https://users.roblox.com/v1/users/{user_id}"
            user_response = self.session.get(user_url, timeout=10)

            if user_response.status_code != 200:
                print(f"❌ User not found: {user_id}")
                return None

            user_data = user_response.json()
            print(f"✅ User found: {user_data.get('name')}")

            avatar_url = self.fetch_avatar_thumbnail_url(user_id)
            presence = self.fetch_presence(user_id)

            return {
                'userId': user_id,
                'username': user_data.get('name'),
                'description': user_data.get('description', 'No description'),
                'avatarUrl': avatar_url,
                'presence': presence,
                'isNPC': user_data.get('isNPC', False)
            }

        except Exception as e:
            print(f"❌ Error fetching avatar: {e}")
            return None


    def fetch_avatar_3d_meta(self, user_id):
        """Hits Roblox's real 3D thumbnail API and returns obj/mtl/texture hashes.

        Since March 23, 2026, this endpoint requires an Open Cloud API key
        (x-api-key header) with 'thumbnails: read' permission -- unauthenticated
        requests get a 403/401. See ROBLOX_API_KEY setup notes above.
        """
        if not ROBLOX_API_KEY:
            raise RuntimeError(
                "No Roblox API key set. Roblox now requires auth for 3D thumbnails "
                "(since March 2026). Create a free key at "
                "https://create.roblox.com/dashboard/credentials (permission: "
                "Thumbnails -> read), then set env var ROBLOX_API_KEY and restart the server."
            )

        meta_url = f"https://thumbnails.roblox.com/v1/users/avatar-3d?userId={user_id}"
        headers = {'x-api-key': ROBLOX_API_KEY}

        meta_resp = self.session.get(meta_url, headers=headers, timeout=10)
        if meta_resp.status_code in (401, 403):
            raise RuntimeError(
                f"Roblox rejected the API key (HTTP {meta_resp.status_code}). "
                "Check the key is valid and has 'Thumbnails: read' permission."
            )
        meta_resp.raise_for_status()
        meta = meta_resp.json()

        state = meta.get('state')
        if state != 'Completed' or not meta.get('imageUrl'):
            raise RuntimeError(f"3D model not ready (state: {state})")

        # imageUrl is misleadingly named -- it's actually a JSON blob, not an image.
        # This lives on the CDN (t*.rbxcdn.com), which isn't behind the same auth wall.
        data_resp = self.session.get(meta['imageUrl'], timeout=10)
        data_resp.raise_for_status()
        data = data_resp.json()

        return {
            'obj': data['obj'],
            'mtl': data['mtl'],
            'textures': data['textures']
        }


avatar_fetcher = AvatarFetcher()


@app.route('/')
def index():
    # Get ESP settings from globals if they were set via command-line
    esp_skeleton = globals().get('esp_skeleton', True)
    esp_box = globals().get('esp_box', True)
    esp_box_fill = globals().get('esp_box_fill', False)
    esp_corner_box = globals().get('esp_corner_box', False)
    esp_name_tag = globals().get('esp_name_tag', True)
    esp_distance = globals().get('esp_distance', True)
    
    # Create init script for ESP checkboxes and real-time signal listening
    esp_init_script = '''
    <script>
    // Real-time ESP signal listener from C++
    window.espSignalListener = setInterval(async function() {
        try {
            // Poll for ESP signals from C++
            const response = await fetch('http://localhost:5000/api/esp-signal/poll', {
                method: 'GET',
                cache: 'no-store'
            }).catch(() => null);
            
            if(response && response.ok) {
                const data = await response.json();
                if(data.pending && data.pending.length > 0) {
                    data.pending.forEach(signal => {
                        const checkbox = document.getElementById(signal.checkbox_id);
                        if(checkbox && checkbox.checked !== signal.enabled) {
                            checkbox.checked = signal.enabled;
                            checkbox.dispatchEvent(new Event('change', { bubbles: true }));
                        }
                    });
                }
            }
        } catch(e) {
            // silently fail if server not responding
        }
    }, 200);
    
    document.addEventListener('DOMContentLoaded', function() {
        setTimeout(function() {
            // Initialize ESP overlay checkboxes from startup settings
            if(document.getElementById('espChkBox')) document.getElementById('espChkBox').checked = %s;
            if(document.getElementById('espChkCornerBox')) document.getElementById('espChkCornerBox').checked = %s;
            if(document.getElementById('espChkFill')) document.getElementById('espChkFill').checked = %s;
            if(document.getElementById('espChkName')) document.getElementById('espChkName').checked = %s;
            if(document.getElementById('espChkDistance')) document.getElementById('espChkDistance').checked = %s;
            
            // Add skeleton checkbox to ESP panel if it doesn't exist
            const espPanel = document.getElementById('espPanel');
            if(espPanel && !document.getElementById('espChkSkeleton')) {
                const skeletonLabel = document.createElement('label');
                skeletonLabel.innerHTML = '<input type="checkbox" id="espChkSkeleton" onchange="if(this.checked != skeletonVisible) toggleSkeleton()"> Skeleton';
                espPanel.insertBefore(skeletonLabel, espPanel.querySelector('.esp-hint'));
                document.getElementById('espChkSkeleton').checked = %s;
            }
            
            // Initialize skeleton based on startup parameter
            if(%s && typeof toggleSkeleton === 'function') {
                if(!skeletonVisible) {
                    toggleSkeleton();
                }
            }
        }, 100);
    });
    </script>
    ''' % ('true' if esp_box else 'false', 'true' if esp_corner_box else 'false', 
           'true' if esp_box_fill else 'false', 'true' if esp_name_tag else 'false', 
           'true' if esp_distance else 'false', 'true' if esp_skeleton else 'false',
           'true' if esp_skeleton else 'false')
    
    return render_template_string(PAGE_HTML + esp_init_script, last_profile=globals().get('initial_player_name', load_last_profile()), sidebar_collapsed=load_sidebar_collapsed(), ui=load_ui_settings(), camera_view=load_camera_view())


@app.route('/api/avatar/<user_id>', methods=['GET'])
def get_avatar(user_id):
    print(f"\n🔍 Request for user: {user_id}")
    try:
        avatar_data = avatar_fetcher.fetch_avatar_data(user_id)
        if avatar_data:
            return jsonify(avatar_data), 200
        return jsonify({'error': 'User not found or invalid ID'}), 404
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/avatar3d/<user_id>', methods=['GET'])
def get_avatar_3d(user_id):
    """Kicks off the real 3D model fetch and returns proxy URLs for the frontend."""
    print(f"\n🧊 3D model request for user: {user_id}")
    try:
        if not str(user_id).isdigit():
            resolved_id = avatar_fetcher.resolve_username_to_id(user_id)
            if not resolved_id:
                return jsonify({'error': f"Username '{user_id}' not found"}), 404
            user_id = resolved_id
        meta = avatar_fetcher.fetch_avatar_3d_meta(user_id)
        MODEL_CACHE[user_id] = meta
        return jsonify({
            'objUrl': f'/api/model/{user_id}/mesh.obj',
            'mtlUrl': f'/api/model/{user_id}/mesh.mtl',
            'textureCount': len(meta['textures'])
        }), 200
    except Exception as e:
        print(f"❌ 3D model error: {e}")
        return jsonify({'error': str(e)}), 502


@app.route('/api/model/<user_id>/mesh.obj', methods=['GET'])
def get_model_obj(user_id):
    cache = MODEL_CACHE.get(user_id)
    if not cache:
        return jsonify({'error': 'No cached model -- call /api/avatar3d first'}), 404
    try:
        cdn_url = resolve_cdn_url(cache['obj'])
        resp = avatar_fetcher.session.get(cdn_url, timeout=15)
        resp.raise_for_status()
        obj_text = "mtllib mesh.mtl\n\n" + resp.text
        return Response(obj_text, mimetype='text/plain')
    except Exception as e:
        print(f"❌ mesh.obj proxy failed for {user_id} ({cdn_url}): {e}")
        return jsonify({'error': f'Failed to fetch OBJ from CDN: {e}'}), 502


@app.route('/api/model/<user_id>/mesh.mtl', methods=['GET'])
def get_model_mtl(user_id):
    cache = MODEL_CACHE.get(user_id)
    if not cache:
        return jsonify({'error': 'No cached model -- call /api/avatar3d first'}), 404
    try:
        cdn_url = resolve_cdn_url(cache['mtl'])
        resp = avatar_fetcher.session.get(cdn_url, timeout=15)
        resp.raise_for_status()
        mtl_text = resp.text
        for idx, tex_hash in enumerate(cache['textures']):
            mtl_text = mtl_text.replace(tex_hash, f'tex_{idx}.png')
        return Response(mtl_text, mimetype='text/plain')
    except Exception as e:
        print(f"❌ mesh.mtl proxy failed for {user_id} ({cdn_url}): {e}")
        return jsonify({'error': f'Failed to fetch MTL from CDN: {e}'}), 502


@app.route('/api/model/<user_id>/tex_<int:idx>.png', methods=['GET'])
def get_model_texture(user_id, idx):
    cache = MODEL_CACHE.get(user_id)
    if not cache or idx >= len(cache['textures']):
        return jsonify({'error': 'Texture not found'}), 404
    try:
        tex_hash = cache['textures'][idx]
        cdn_url = resolve_cdn_url(tex_hash)
        resp = avatar_fetcher.session.get(cdn_url, timeout=15)
        resp.raise_for_status()
        return Response(resp.content, mimetype='image/png')
    except Exception as e:
        print(f"❌ texture proxy failed for {user_id} idx {idx} ({cdn_url}): {e}")
        return jsonify({'error': f'Failed to fetch texture from CDN: {e}'}), 502


@app.route('/api/last-profile', methods=['POST'])
def set_last_profile():
    from flask import request
    body = request.get_json(silent=True, force=True) or {}
    query = str(body.get('query', '')).strip()
    if query:
        save_last_profile(query)
    return jsonify({'ok': bool(query)}), 200


@app.route('/api/sidebar-state', methods=['POST'])
def set_sidebar_state():
    from flask import request
    body = request.get_json(silent=True, force=True) or {}
    save_sidebar_collapsed(body.get('collapsed', False))
    return jsonify({'ok': True}), 200


ESP_SIGNAL_CODE_MAP = {
    1: 'espBox',        # Box (outline around the character)
    2: 'espCornerBox',  # Corner box
    3: 'espFill',       # Box fill
    4: 'espDistance',   # Distance
    5: 'espHealth',     # Health bar
    6: 'espName',       # Name tag
    7: 'skeleton',      # 3D skeleton/bones overlay (separate from the ESP box)
}


@app.route('/api/ui-settings', methods=['GET', 'POST'])
def set_ui_settings():
    from flask import request
    if request.method == 'GET':
        return jsonify(load_ui_settings()), 200
    body = request.get_json(silent=True, force=True) or {}
    save_ui_settings(body)
    return jsonify({'ok': True}), 200


@app.route('/api/esp-signal/<int:code>', methods=['GET', 'POST'])
def esp_signal(code):
    """External control channel: hit this from your own script to flip one overlay
    feature on/off by number, e.g. GET /api/esp-signal/1 to turn Box on, or
    GET /api/esp-signal/1?enable=0 to turn it off. If the app window is open, it
    picks up the change within ~1 second via its settings poll.
    """
    from flask import request
    key = ESP_SIGNAL_CODE_MAP.get(code)
    if key is None:
        return jsonify({'error': f'Unknown code {code}. Valid codes: 1-7.'}), 400
    if request.method == 'POST':
        body = request.get_json(silent=True, force=True) or {}
        enabled = bool(body.get('enable', True))
    else:
        enabled = request.args.get('enable', '1') not in ('0', 'off', 'false', 'no')
    save_ui_settings({key: enabled})
    return jsonify({'ok': True, 'code': code, 'setting': key, 'enabled': enabled}), 200


@app.route('/api/camera-view', methods=['POST'])
def set_camera_view():
    from flask import request
    body = request.get_json(silent=True, force=True) or {}
    save_camera_view(body)
    return jsonify({'ok': True}), 200


@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({'status': 'running', 'version': '2.0', 'mode': 'production'}), 200


@app.route('/api/set-visibility', methods=['POST'])
def set_visibility():
    """Hide or show the window"""
    data = request.get_json() or {}
    should_hide = data.get('hide', False)
    
    # This will be called from the webview side
    # For now, just acknowledge the request
    return jsonify({'success': True, 'hidden': should_hide})

@app.route('/api/set-window-position', methods=['POST'])
def set_window_position():
    """Called by C++ to position this window as a sidebar panel.
    
    JSON body: {"x": int, "y": int}
    Used to align the webview window to the left of Skidatron's menu overlay.
    """
    from flask import request
    try:
        data = request.get_json() or {}
        x = int(data.get('x', 0))
        y = int(data.get('y', 0))
        
        # Get the Api instance's window reference and move it
        # This will be set by the main code after webview.create_window()
        if hasattr(api, '_window') and api._window:
            api._window.move(x, y)
            return jsonify({'success': True, 'x': x, 'y': y}), 200
        else:
            return jsonify({'success': False, 'error': 'window_not_ready'}), 503
    except Exception as e:
        print(f"⚠️ Error setting window position: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400


def wait_for_server(host='localhost', port=5000, timeout=5.0):
    """Blocks until the Flask server is actually accepting connections.

    Without this, the webview window can open and try to load the page
    before Flask has finished binding the port, which shows up as a blank
    white window (the load simply failed with nothing to retry it).
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return True
        except OSError:
            time.sleep(0.05)
    return False


class Api:
    """Exposed to the page as `window.pywebview.api.*` so JS can control the
    native window itself (things CSS/JS alone can't do, like hiding the OS
    title bar).

    IMPORTANT: the window reference MUST be a private attribute (leading
    underscore). pywebview's js_api injection recursively walks every
    *public* attribute of this object to build the JS bridge -- if the
    window object itself is public, that walk follows it straight into the
    native WinForms object graph, hits Rectangle.Empty (which returns a
    fresh instance on every access, so pywebview's dedup-by-id can't catch
    the cycle), and recurses until Python blows the stack. That's the
    'window.native.AccessibilityObject.Bounds.Empty.Empty...: maximum
    recursion depth exceeded' error. Keeping it as `_window` makes
    pywebview skip it during that walk.
    """
    def __init__(self):
        self._window = None  # set right after webview.create_window() returns

    def toggle_fullscreen(self):
        if self._window:
            self._window.toggle_fullscreen()


if __name__ == '__main__':
    print("""
+========================================+
|  Roblox Avatar Viewer (WORKING)         |
|         Python Flask Backend            |
+========================================+
    """)
    if not ROBLOX_API_KEY:
        print("⚠️  No API key found -- 3D models will fail to load.")
        print("   Get a free key at https://create.roblox.com/dashboard/credentials")
        print("   (permission: Thumbnails -> read), then save it in apikey.txt")
        print("   in this same folder.\n")
    print("Starting server on http://localhost:5000")
    print("Try loading a real Roblox user\n")

    # Parse command-line arguments from C++
    initial_player_name = '1'  # Default to Roblox creator
    esp_skeleton = True
    esp_box = True
    esp_box_fill = False
    esp_corner_box = False
    esp_name_tag = True
    esp_distance = True
    
    try:
        if len(sys.argv) > 1:
            initial_player_name = sys.argv[1]
            print(f"[*] Launching with player: {initial_player_name}")
            
            # Parse ESP settings if provided as additional arguments
            if len(sys.argv) > 2:
                esp_skeleton = sys.argv[2].lower() in ('1', 'true', 'yes')
            if len(sys.argv) > 3:
                esp_box = sys.argv[3].lower() in ('1', 'true', 'yes')
            if len(sys.argv) > 4:
                esp_box_fill = sys.argv[4].lower() in ('1', 'true', 'yes')
            if len(sys.argv) > 5:
                esp_corner_box = sys.argv[5].lower() in ('1', 'true', 'yes')
            if len(sys.argv) > 6:
                esp_name_tag = sys.argv[6].lower() in ('1', 'true', 'yes')
            if len(sys.argv) > 7:
                esp_distance = sys.argv[7].lower() in ('1', 'true', 'yes')
            print(f"[*] ESP Settings: Skeleton={esp_skeleton}, Box={esp_box}, Fill={esp_box_fill}, Corner={esp_corner_box}, Name={esp_name_tag}, Distance={esp_distance}")
    except Exception as e:
        print(f"[!] Error parsing arguments: {e}")
        import traceback
        traceback.print_exc()
    
    # Make them globally accessible to the route handlers
    globals()['initial_player_name'] = initial_player_name
    globals()['esp_skeleton'] = esp_skeleton
    globals()['esp_box'] = esp_box
    globals()['esp_box_fill'] = esp_box_fill
    globals()['esp_corner_box'] = esp_corner_box
    globals()['esp_name_tag'] = esp_name_tag
    globals()['esp_distance'] = esp_distance

    server_thread = threading.Thread(
        target=lambda: app.run(debug=False, host='localhost', port=5000, use_reloader=False),
        daemon=True
    )
    server_thread.start()

    if not wait_for_server():
        print("⚠️ Server didn't come up in time -- the window may load blank. Try restarting.")

    saved_size = load_window_size()
    current_size = dict(saved_size)  # tracks the latest known size as the user resizes

    saved_position = load_window_position()
    # Tracks the latest known screen position as the user drags the window.
    # Starts at whatever was saved, or (0, 0) on the very first launch --
    # the 'moved' event fires immediately once the OS places the window, so
    # this gets corrected right away regardless.
    current_position = dict(saved_position) if saved_position else {'x': 0, 'y': 0}

    # Native desktop window (no browser chrome) instead of a browser tab.
    # x/y are omitted (left as None -> OS default placement) on the very
    # first launch, before any position has ever been saved.
    window_kwargs = {
        'width': saved_size['width'],
        'height': saved_size['height'],
        'min_size': (200, 300),
        'resizable': True,
        'on_top': True,
        'frameless': True
    }
    if saved_position:
        window_kwargs['x'] = saved_position['x']
        window_kwargs['y'] = saved_position['y']

    api = Api()

    window = webview.create_window(
        'Roblox 3D Avatar Viewer',
        'http://localhost:5000',
        js_api=api,
        **window_kwargs
    )
    api._window = window

    def on_resized(width, height):
        current_size['width'] = width
        current_size['height'] = height

    def on_moved(x, y):
        current_position['x'] = x
        current_position['y'] = y

    def on_closing():
        save_window_size(current_size)
        save_window_position(current_position)

    window.events.resized += on_resized
    window.events.moved += on_moved
    window.events.closing += on_closing

    webview.start()
