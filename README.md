# Miniature Origin Setter — Blender Add-on

A Blender add-on that automatically repositions the origin of 3D-print miniature STL files to the centroid of their base surface, then moves the object to world origin (0, 0, 0).

Replaces a tedious manual workflow (select bottom verts → duplicate → flatten → separate → set origin → snap → cursor → set origin → move → delete helper mesh) with a single button click.

---

## Features

- **Single piece** — sets the origin of the active object (or all selected meshes at once) to the area-weighted centroid of its bottom surface.
- **Multi-part miniatures** — uses the active object as the base, applies the same shared origin to every selected part, then moves them all to (0, 0, 0) preserving their relative positions.
- **Configurable tolerance** — controls how far above the lowest point a vertex can be and still be considered part of the base (useful for uneven or terrain-style bases).
- Non-destructive: 3D cursor and selection are restored after every operation.
- Full **Undo** support (`Ctrl+Z`).

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

### Single Piece

1. Select the miniature mesh.
2. Adjust **Bottom Tolerance** if needed (default `0.001` works well for mm-scale STLs).
3. Enable **Mover para Origem do Mundo** (on by default).
4. Optionally enable **Processar Todos Selecionados** to batch-process every selected mesh.
5. Click **Definir Origem da Miniatura**.

### Multi-Part Miniature

1. Select **all parts** of the miniature (body, weapons, accessories, etc.).
2. **Ctrl+Click** the **base** last so it becomes the active object (brighter orange outline).
3. Click **Definir Origem (Múltiplas Partes)**.

All parts receive the same origin (the base's bottom centroid) and are moved together to (0, 0, 0), maintaining their relative positions.

---

## How it works

The add-on replicates the manual workflow mathematically, without creating any helper mesh:

1. Finds the world-space minimum Z of the mesh.
2. Collects all faces that have at least one vertex within `tolerance` of that minimum.
3. Projects those faces onto the XY plane (Z = 0) and calculates their **area-weighted centroid** — equivalent to Blender's *Origin to Center of Mass (Surface)* on a flattened copy.
4. Places the 3D cursor at `(centroid_X, centroid_Y, min_Z)` in world space.
5. Applies **Set Origin → Origin to 3D Cursor** on the target object(s).
6. Moves each object to `(0, 0, 0)`.
7. Restores the 3D cursor and selection to their previous state.

---

## License

[GPL-2.0-or-later](https://spdx.org/licenses/GPL-2.0-or-later.html)
