"""
Render a .glb 3D model as an interactive matplotlib window (no browser needed).

Install:
    pip install trimesh matplotlib numpy pillow

Run:
    python render_avatar.py

Controls in the window:
    - Left-click + drag on the 3D view       : rotate
    - Right-click + drag on the 3D view      : zoom
    - Middle-click + drag on the 3D view     : pan
    - Left-click + drag the thin top strip   : move the window
    - Left-click + drag the bottom-right dot : resize the window
    - '=' / '-'                              : also grow/shrink via keyboard
    - Escape                                 : close (no title bar / X button)
"""

import numpy as np
import matplotlib
matplotlib.rcParams["toolbar"] = "None"
import trimesh
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

MODEL_PATH = r"C:\Users\g2615\Downloads\noob_-_roblox.glb"   # change to your file path
OUTPUT_PATH = r"C:\Users\g2615\Downloads\avatar_render.png"

# Window size in pixels — change these to whatever fits your screen
WINDOW_WIDTH = 500
WINDOW_HEIGHT = 650

# Camera / view settings
ELEV = 8        # up/down angle
AZIM = -70      # left/right angle
BG_COLOR = "#1b1d22"


def load_scene(path):
    scene = trimesh.load(path)
    if isinstance(scene, trimesh.Scene):
        return scene
    # single mesh fallback
    s = trimesh.Scene()
    s.add_geometry(scene)
    return s


def render(path, output):
    scene = load_scene(path)

    dpi = 100
    fig = plt.figure(figsize=(WINDOW_WIDTH / dpi, WINDOW_HEIGHT / dpi), dpi=dpi)
    fig.patch.set_facecolor(BG_COLOR)
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor(BG_COLOR)

    all_verts = []

    for name, geom in scene.geometry.items():
        # world transform for this geometry (in case scene has multiple nodes)
        transforms = scene.graph.geometry_nodes.get(name, [])
        matrix = np.eye(4)
        if transforms:
            matrix = scene.graph.get(transforms[0])[0]

        verts = trimesh.transform_points(geom.vertices, matrix)
        # matplotlib's 3D axes always treat Z as "up" — this model's height
        # is along Y, so swap Y and Z for plotting purposes only.
        verts = verts[:, [0, 2, 1]]
        faces = geom.faces
        all_verts.append(verts)

        # per-face average color from texture/vertex colors
        try:
            vcolors = geom.visual.to_color().vertex_colors[:, :3] / 255.0
            face_colors = vcolors[faces].mean(axis=1)
        except Exception:
            face_colors = np.tile([0.7, 0.7, 0.7], (len(faces), 1))

        triangles = verts[faces]
        poly = Poly3DCollection(triangles, facecolor=face_colors,
                                 edgecolor="none", linewidths=0)
        ax.add_collection3d(poly)

    all_verts = np.vstack(all_verts)
    mins, maxs = all_verts.min(axis=0), all_verts.max(axis=0)
    centers = (mins + maxs) / 2
    max_range = (maxs - mins).max() / 2

    ax.set_xlim(centers[0] - max_range, centers[0] + max_range)
    ax.set_ylim(centers[1] - max_range, centers[1] + max_range)
    ax.set_zlim(centers[2] - max_range, centers[2] + max_range)

    ax.set_box_aspect([1, 1, 1])
    ax.view_init(elev=ELEV, azim=AZIM)
    ax.set_axis_off()

    # Strip the OS title bar too, and replace it with a custom drag strip
    # (top) and resize grip (bottom-right corner) so the window can still
    # be moved and resized with the mouse.
    try:
        mgr = plt.get_current_fig_manager()
        backend = matplotlib.get_backend().lower()
        if "tk" in backend:
            import tkinter as tk

            root = mgr.window
            canvas_widget = mgr.canvas.get_tk_widget()
            canvas_widget.pack_forget()

            root.update_idletasks()
            root.overrideredirect(True)
            root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")

            drag_bar = tk.Frame(root, bg="#3a6ea5", height=26, cursor="fleur")
            drag_bar.pack(side="top", fill="x")
            drag_label = tk.Label(drag_bar, text="≡  drag here to move window",
                                   bg="#3a6ea5", fg="white", font=("Segoe UI", 9),
                                   cursor="fleur")
            drag_label.pack(side="left", padx=6)

            canvas_widget.pack(side="top", fill="both", expand=True)

            grip = tk.Label(root, text="◢", bg="#3a6ea5", fg="white",
                             font=("Segoe UI", 12, "bold"),
                             cursor="bottom_right_corner")
            grip.place(relx=1.0, rely=1.0, anchor="se", width=22, height=22)

            def start_move(event):
                root._drag_x = event.x
                root._drag_y = event.y

            def do_move(event):
                x = root.winfo_pointerx() - root._drag_x
                y = root.winfo_pointery() - root._drag_y
                root.geometry(f"+{x}+{y}")

            drag_bar.bind("<ButtonPress-1>", start_move)
            drag_bar.bind("<B1-Motion>", do_move)
            drag_label.bind("<ButtonPress-1>", start_move)
            drag_label.bind("<B1-Motion>", do_move)

            def start_resize(event):
                root._resize_x = event.x_root
                root._resize_y = event.y_root
                root._start_w = root.winfo_width()
                root._start_h = root.winfo_height()

            def do_resize(event):
                dx = event.x_root - root._resize_x
                dy = event.y_root - root._resize_y
                w = max(250, root._start_w + dx)
                h = max(250, root._start_h + dy)
                root.geometry(f"{w}x{h}")

            grip.bind("<ButtonPress-1>", start_resize)
            grip.bind("<B1-Motion>", do_resize)

            root.update()
        elif "qt" in backend:
            from matplotlib.backends.qt_compat import QtWidgets, QtCore

            win = mgr.window
            canvas = mgr.canvas

            win.setWindowFlags(win.windowFlags() | QtCore.Qt.FramelessWindowHint)
            win.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

            container = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout(container)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)

            drag_bar = QtWidgets.QLabel("\u2261  drag here to move window")
            drag_bar.setStyleSheet(
                "background-color:#3a6ea5; color:white; padding:5px; font-size:12px;"
            )
            drag_bar.setFixedHeight(26)
            layout.addWidget(drag_bar)
            layout.addWidget(canvas)

            bottom_row = QtWidgets.QHBoxLayout()
            bottom_row.addStretch(1)
            size_grip = QtWidgets.QSizeGrip(container)
            size_grip.setFixedSize(22, 22)
            size_grip.setStyleSheet("background-color:#3a6ea5;")
            bottom_row.addWidget(size_grip)
            layout.addLayout(bottom_row)

            win.setCentralWidget(container)
            win.show()

            drag_state = {}

            def _pt(event):
                # PyQt6/PySide6 use globalPosition(); PyQt5/PySide2 use globalPos()
                gp = event.globalPosition().toPoint() if hasattr(event, "globalPosition") else event.globalPos()
                return gp

            def press(event):
                drag_state["offset"] = _pt(event) - win.frameGeometry().topLeft()

            def move(event):
                if "offset" in drag_state:
                    win.move(_pt(event) - drag_state["offset"])

            drag_bar.mousePressEvent = press
            drag_bar.mouseMoveEvent = move
    except Exception as e:
        print("Could not remove title bar:", e)

    def on_key(event):
        if event.key == "escape":
            plt.close(fig)
            return
        step = 60
        try:
            backend = matplotlib.get_backend().lower()
            if "tk" in backend:
                root = mgr.window
                w = root.winfo_width()
                h = root.winfo_height()
                if event.key == "=":
                    w, h = w + step, h + step
                elif event.key == "-":
                    w, h = max(200, w - step), max(200, h - step)
                else:
                    return
                root.geometry(f"{w}x{h}")
            elif "qt" in backend:
                win = mgr.window
                w, h = win.width(), win.height()
                if event.key == "=":
                    w, h = w + step, h + step
                elif event.key == "-":
                    w, h = max(200, w - step), max(200, h - step)
                else:
                    return
                win.resize(w, h)
        except Exception as e:
            print("Could not resize window:", e)

    fig.canvas.mpl_connect("key_press_event", on_key)

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    render(MODEL_PATH, OUTPUT_PATH)