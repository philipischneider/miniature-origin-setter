# Miniature Origin Setter — Blender Add-on

A Blender add-on designed for the 3D-print miniature workflow. It automates origin repositioning, scene layout, and camera framing — replacing several tedious manual steps with single button clicks.

---

## Features

### Origin Setting
- **Single piece** — sets the origin of the active object (or every selected mesh at once) to the area-weighted centroid of its bottom surface, then moves it to world origin (0, 0, 0).
- **Multi-part miniatures** — designate one part as the base (active object); all selected parts receive the same shared origin derived from the base's bottom centroid and are moved together to (0, 0, 0), preserving their relative positions.
- **Configurable bottom tolerance** — controls how far above the lowest point a vertex can be and still be considered part of the base (useful for uneven or terrain-style bases).

### Layout
- **Distribute** — spreads selected miniatures along the X or Y axis. Spacing is measured between the edges of each miniature's *base bounding box* (vertices within a configurable height above the bottom), not between origins or full-mesh extents.
- **Center at origin** — shifts the entire group so the combined base bounding box center lands at 0 on the chosen axis (X, Y, or both simultaneously), while preserving relative positions between objects.

### Camera Framing
- **Frame camera** — positions and rotates the active camera so that the selected miniatures occupy a specified percentage of the horizontal image width, viewed from a chosen lateral direction (+X, −X, +Y, −Y). Camera up vector is always aligned to world Z. Distance is calculated with a per-corner perspective correction that accounts for the full 3D depth of the bounding box, giving accurate framing for any axis.

### General
- Non-destructive: 3D cursor, selection, and active object are restored after every operation.
- Full **Undo** support (`Ctrl+Z`).
- Compatible with objects that have non-applied scale, rotation, or parent transforms.

---

## Compatibility

| Blender version | Install method |
|---|---|
| 3.0 – 4.1 | Legacy add-on (install the `miniature_origin_setter` folder) |
| 4.2+ | Extension (`blender_manifest.toml` included) |

---

## Installation

### Blender 3.x / 4.0 – 4.1 (legacy add-on)

1. Download or clone this repository.
2. In Blender: **Edit → Preferences → Add-ons → Install**.
3. Select the `miniature_origin_setter` **folder** (zip it first if Blender asks for a `.zip`).
4. Enable the add-on by checking its checkbox.

### Blender 4.2+ (extension)

1. Download or clone this repository.
2. In Blender: **Edit → Preferences → Extensions → Install from Disk**.
3. Select the `miniature_origin_setter` folder.

---

## Usage

Open the **N-panel** (press `N` in the 3D Viewport) and go to the **Miniature** tab.

---

### Origin — Single Piece

| Setting | Description |
|---|---|
| **Tolerância Inferior** | Max distance above the lowest vertex to include in the base calculation |
| **Mover para Origem do Mundo** | Move the object to (0, 0, 0) after setting the origin |
| **Processar Todos Selecionados** | Apply to every selected mesh instead of only the active one |

1. Select the miniature mesh (or all meshes to batch-process).
2. Adjust **Tolerância Inferior** if needed (`0.001` works for mm-scale STLs with flat bases; increase for uneven bases).
3. Click **Definir Origem da Miniatura**.

---

### Origin — Multi-Part Miniature

Used when a miniature is delivered as separate pieces (body, arms, weapon, base, etc.) that must be assembled during printing.

1. Select **all parts** of the miniature.
2. **Ctrl+Click** the **base piece** last so it becomes the active object (highlighted with a brighter orange outline).
3. Click **Definir Origem (Múltiplas Partes)**.

All parts receive the same origin point (the base's bottom centroid) and are moved together to (0, 0, 0). Relative positions between pieces are fully preserved.

---

### Layout — Distribute Miniatures

| Setting | Description |
|---|---|
| **Altura da Base** | Height slice from the bottom used to compute each miniature's base bounding box. Geometry above this value (arms, weapons, etc.) is ignored for spacing purposes |
| **Espaçamento** | Gap between adjacent base bounding box edges |
| **Posição Inicial** | World-space position where the first miniature's base bounding box edge is placed |
| **Eixo** | X, Y, or X+Y (X+Y is only valid for Center, not Distribute) |

1. Select all miniatures to distribute (2 or more).
2. Set **Altura da Base** to roughly the height of the bases (e.g. 3–5 mm).
3. Set the desired **Espaçamento** between bases.
4. Choose **Eixo** (X or Y).
5. Click **Distribuir Miniaturas**.

Objects are sorted by their current bounding box position along the chosen axis before placement.

> **Note:** The Distribute button is disabled when **X+Y** is selected, since distribution requires a single axis.

---

### Layout — Center at Origin

Shifts the entire group so the combined base bounding box center lands at 0 on the chosen axis. Relative positions between objects are preserved.

1. Select all miniatures.
2. Choose **Eixo** (X, Y, or X+Y to center on both axes simultaneously).
3. Click **Centralizar na Origem**.

Reuses the same **Altura da Base** and **Eixo** settings as Distribute.

---

### Camera Framing

| Setting | Description |
|---|---|
| **Preenchimento Horizontal** | Percentage of the image width the miniatures should occupy (1–99 %) |
| **Eixo / Lado** | Side from which the camera views the miniatures: +X, −X, +Y, −Y |

1. Make sure the scene has an active camera (shown in the panel header).
2. Select all miniature meshes to include in the framing calculation.
3. Set the desired **Preenchimento Horizontal** (e.g. 80 %).
4. Choose the viewing **Eixo / Lado**.
5. Click **Enquadrar Câmera**.

The operator sets both the camera **position** and **rotation**:
- The camera is placed at the chosen side of the combined 3D bounding box of all selected meshes.
- The view plane is aligned with the bounding box (lateral view, camera up = world Z).
- The distance is calculated with a per-corner perspective correction so the outermost corner of the nearest bounding box face exactly meets the fill boundary — accurate for any axis and any bounding box aspect ratio.

> Only perspective cameras are supported. Orthographic cameras are not.

---

## How origin setting works

The add-on replicates the manual workflow mathematically, without creating any helper mesh:

1. Finds the world-space minimum Z of the mesh.
2. Collects all faces that have at least one vertex within `tolerance` of that minimum.
3. Projects those faces onto the XY plane and calculates their **area-weighted centroid** — equivalent to Blender's *Origin to Center of Mass (Surface)* on a flattened copy.
4. Places the 3D cursor at `(centroid_X, centroid_Y, min_Z)` in world space.
5. Applies **Set Origin → Origin to 3D Cursor** on the target object(s).
6. Moves each object to `(0, 0, 0)`.
7. Restores the 3D cursor and selection.

---

## How camera framing works

For each of the 8 corners of the combined AABB, the minimum camera distance that keeps that corner within the fill fraction is:

```
D_corner = |cam_x · (c − center)| / (fill · tan(h_fov / 2))  −  look_dir · (c − center)
```

The second term corrects for the corner's depth offset from the bbox center. The final distance is `max(D_corner)` over all 8 corners — the exact distance where the nearest, outermost corner just touches the fill boundary.

The horizontal FOV is derived from `sensor_width`, `lens` (focal length), `sensor_fit`, and the render aspect ratio, supporting all of Blender's sensor fit modes (AUTO, HORIZONTAL, VERTICAL).

---

## License

[GPL-2.0-or-later](https://spdx.org/licenses/GPL-2.0-or-later.html)
