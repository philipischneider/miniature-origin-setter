bl_info = {
    "name": "Miniature Origin Setter",
    "author": "philipischneider",
    "version": (1, 1, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Miniature",
    "description": (
        "Reposiciona automaticamente a origem de miniaturas STL para o centroide "
        "da superfície inferior, depois move o objeto para a origem do mundo (0,0,0)."
    ),
    "category": "Object",
}

import bpy
import bmesh
from mathutils import Vector


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def get_bottom_centroid(obj, tolerance):
    """
    Calcula o centroide ponderado pela área da superfície inferior do mesh.

    Replica o fluxo manual:
      1. Selecionar vértices próximos ao limite inferior (dentro de `tolerance`)
      2. Duplicar e achatar no eixo Z → malha plana
      3. Calcular "Origin to Center of Mass (Surface)" dessa malha plana
      4. Usar a posição resultante como nova origem (X, Y do centroide, Z = mínimo)

    Retorna um Vector com a posição em espaço mundo.
    """
    mesh = obj.data
    matrix = obj.matrix_world

    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    if not bm.verts:
        bm.free()
        return None

    # Encontrar Z mínimo em espaço mundo
    min_z = min((matrix @ v.co).z for v in bm.verts)
    threshold = min_z + tolerance

    total_area = 0.0
    weighted_x = 0.0
    weighted_y = 0.0

    for face in bm.faces:
        face_world_verts = [(matrix @ v.co) for v in face.verts]

        # Incluir face se ao menos um vértice estiver dentro da tolerância inferior
        face_min_z = min(v.z for v in face_world_verts)
        if face_min_z > threshold:
            continue

        # Projetar vértices para Z=0 (aplanar) e calcular centroide ponderado por área
        projected = [Vector((v.x, v.y, 0.0)) for v in face_world_verts]

        # Triangulação em leque a partir do primeiro vértice
        v0 = projected[0]
        for i in range(1, len(projected) - 1):
            v1 = projected[i]
            v2 = projected[i + 1]
            cross = (v1 - v0).cross(v2 - v0)
            area = abs(cross.z) / 2.0
            if area > 1e-12:
                tri_centroid = (v0 + v1 + v2) / 3.0
                weighted_x += tri_centroid.x * area
                weighted_y += tri_centroid.y * area
                total_area += area

    bm.free()

    if total_area > 1e-12:
        return Vector((weighted_x / total_area, weighted_y / total_area, min_z))

    # Fallback: média simples dos vértices inferiores (mesh sem faces)
    world_verts = [(matrix @ v.co) for v in mesh.vertices]
    bottom_verts = [v for v in world_verts if v.z <= threshold] or world_verts
    avg_x = sum(v.x for v in bottom_verts) / len(bottom_verts)
    avg_y = sum(v.y for v in bottom_verts) / len(bottom_verts)
    return Vector((avg_x, avg_y, min_z))


# ---------------------------------------------------------------------------
# Operator – peça única (ou lote de peças independentes)
# ---------------------------------------------------------------------------

class MINIATURE_OT_set_origin(bpy.types.Operator):
    """Reposiciona a origem para o centroide da base da miniatura e move para (0,0,0)"""
    bl_idname = "miniature.set_origin"
    bl_label = "Definir Origem da Miniatura"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: bpy.props.FloatProperty(
        name="Tolerância Inferior",
        description=(
            "Distância máxima acima do ponto mais baixo para considerar um vértice "
            "como parte da base. Aumente se a base não for perfeitamente plana."
        ),
        default=0.001,
        min=0.0,
        soft_max=10.0,
        precision=4,
        unit='LENGTH',
    )

    move_to_origin: bpy.props.BoolProperty(
        name="Mover para Origem do Mundo",
        description="Após definir a origem, move o objeto para a posição (0, 0, 0)",
        default=True,
    )

    process_all_selected: bpy.props.BoolProperty(
        name="Processar Todos Selecionados",
        description="Aplica a operação em todos os objetos de mesh selecionados",
        default=False,
    )

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        targets = []

        if self.process_all_selected:
            targets = [o for o in context.selected_objects if o.type == 'MESH']
        else:
            obj = context.active_object
            if obj and obj.type == 'MESH':
                targets = [obj]

        if not targets:
            self.report({'ERROR'}, "Nenhum objeto de mesh selecionado.")
            return {'CANCELLED'}

        # Salvar estado do cursor 3D e da seleção
        saved_cursor_loc = context.scene.cursor.location.copy()
        saved_cursor_rot = context.scene.cursor.rotation_euler.copy()
        saved_active = context.view_layer.objects.active
        saved_selection = list(context.selected_objects)

        processed = 0
        for obj in targets:
            new_origin = get_bottom_centroid(obj, self.tolerance)
            if new_origin is None:
                self.report({'WARNING'}, f"'{obj.name}': mesh vazio, ignorado.")
                continue

            # Isolar seleção para este objeto — origin_set age em todos selecionados
            for o in context.selected_objects:
                o.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj

            context.scene.cursor.location = new_origin
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')

            if self.move_to_origin:
                obj.location = Vector((0.0, 0.0, 0.0))

            processed += 1

        # Restaurar cursor e seleção original
        context.scene.cursor.location = saved_cursor_loc
        context.scene.cursor.rotation_euler = saved_cursor_rot
        for o in saved_selection:
            o.select_set(True)
        context.view_layer.objects.active = saved_active

        self.report({'INFO'}, f"{processed} objeto(s) processado(s) com sucesso.")
        return {'FINISHED'}

    def invoke(self, context, event):
        scene = context.scene
        self.tolerance = scene.miniature_tolerance
        self.move_to_origin = scene.miniature_move_to_origin
        self.process_all_selected = scene.miniature_process_all_selected
        return self.execute(context)


# ---------------------------------------------------------------------------
# Operator – miniatura em múltiplas partes
# ---------------------------------------------------------------------------

class MINIATURE_OT_set_origin_multipart(bpy.types.Operator):
    """
    Miniatura em partes: usa o objeto ATIVO como base para calcular a origem comum.
    Todos os objetos selecionados recebem a mesma origem (centroide da base),
    depois são movidos juntos para (0, 0, 0), preservando as posições relativas.
    """
    bl_idname = "miniature.set_origin_multipart"
    bl_label = "Definir Origem (Múltiplas Partes)"
    bl_options = {'REGISTER', 'UNDO'}

    tolerance: bpy.props.FloatProperty(
        name="Tolerância Inferior",
        description=(
            "Distância máxima acima do ponto mais baixo da BASE para considerar "
            "um vértice como parte da superfície inferior."
        ),
        default=0.001,
        min=0.0,
        soft_max=10.0,
        precision=4,
        unit='LENGTH',
    )

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        base = context.active_object
        if base is None or base.type != 'MESH':
            self.report({'ERROR'}, "O objeto ATIVO deve ser o mesh da base.")
            return {'CANCELLED'}

        all_parts = [o for o in context.selected_objects if o.type == 'MESH']
        if len(all_parts) < 2:
            self.report(
                {'ERROR'},
                "Selecione todas as partes da miniatura. "
                "O objeto ativo será tratado como a base."
            )
            return {'CANCELLED'}

        # 1. Calcular o centroide inferior da base
        new_origin = get_bottom_centroid(base, self.tolerance)
        if new_origin is None:
            self.report({'ERROR'}, f"'{base.name}': mesh vazio.")
            return {'CANCELLED'}

        # Salvar estado do cursor 3D
        saved_cursor_loc = context.scene.cursor.location.copy()
        saved_cursor_rot = context.scene.cursor.rotation_euler.copy()

        # 2. Posicionar o cursor no centroide da base
        context.scene.cursor.location = new_origin

        # 3. Aplicar "Origin to 3D Cursor" em TODAS as partes (inclusive a base)
        for part in all_parts:
            context.view_layer.objects.active = part
            bpy.ops.object.origin_set(type='ORIGIN_CURSOR', center='MEDIAN')

        # 4. Mover todas as partes para (0, 0, 0) — posições relativas são preservadas
        for part in all_parts:
            part.location = Vector((0.0, 0.0, 0.0))

        # Restaurar cursor
        context.scene.cursor.location = saved_cursor_loc
        context.scene.cursor.rotation_euler = saved_cursor_rot

        # Restaurar objeto ativo original
        context.view_layer.objects.active = base

        self.report(
            {'INFO'},
            f"{len(all_parts)} parte(s) processada(s). Base: '{base.name}'."
        )
        return {'FINISHED'}

    def invoke(self, context, event):
        self.tolerance = context.scene.miniature_tolerance
        return self.execute(context)


# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

class MINIATURE_PT_panel(bpy.types.Panel):
    """Painel lateral para definir a origem de miniaturas"""
    bl_label = "Miniature Origin"
    bl_idname = "MINIATURE_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Miniature'

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        obj = context.active_object

        # --- Configuração comum ---
        box = layout.box()
        box.label(text="Configurações", icon='SETTINGS')
        box.prop(scene, "miniature_tolerance")

        layout.separator()

        # ── Seção: Peça Única ────────────────────────────────────────────────
        box_single = layout.box()
        box_single.label(text="Peça Única", icon='MESH_DATA')

        col = box_single.column(align=True)
        col.prop(scene, "miniature_move_to_origin")
        col.prop(scene, "miniature_process_all_selected")

        row = box_single.row()
        row.scale_y = 1.4
        op = row.operator("miniature.set_origin", icon='OBJECT_ORIGIN')
        op.tolerance = scene.miniature_tolerance
        op.move_to_origin = scene.miniature_move_to_origin
        op.process_all_selected = scene.miniature_process_all_selected

        layout.separator()

        # ── Seção: Múltiplas Partes ──────────────────────────────────────────
        box_multi = layout.box()
        box_multi.label(text="Múltiplas Partes", icon='OUTLINER_OB_GROUP_INSTANCE')

        col = box_multi.column()
        col.label(text="Objeto ativo = BASE da miniatura", icon='INFO')
        col.label(text="Selecione todas as partes + base")

        row = box_multi.row()
        row.scale_y = 1.4
        op_multi = row.operator("miniature.set_origin_multipart", icon='OBJECT_ORIGIN')
        op_multi.tolerance = scene.miniature_tolerance

        layout.separator()

        # --- Info do objeto ativo ---
        if obj is None:
            layout.label(text="Nenhum objeto ativo", icon='ERROR')
        elif obj.type != 'MESH':
            layout.label(text=f"'{obj.name}' não é um mesh", icon='ERROR')
        else:
            layout.label(text=f"Ativo: {obj.name}", icon='MESH_DATA')
            count = sum(1 for o in context.selected_objects if o.type == 'MESH')
            if count > 1:
                layout.label(text=f"{count} mesh(es) selecionado(s)", icon='INFO')


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

_scene_props = [
    ("miniature_tolerance", bpy.props.FloatProperty(
        name="Tolerância Inferior",
        description=(
            "Distância máxima acima do ponto mais baixo para considerar "
            "um vértice como parte da base"
        ),
        default=0.001,
        min=0.0,
        soft_max=10.0,
        precision=4,
        unit='LENGTH',
    )),
    ("miniature_move_to_origin", bpy.props.BoolProperty(
        name="Mover para Origem do Mundo",
        description="Após definir a origem, move o objeto para (0, 0, 0)",
        default=True,
    )),
    ("miniature_process_all_selected", bpy.props.BoolProperty(
        name="Processar Todos Selecionados",
        description="Aplica a operação em todos os meshes selecionados",
        default=False,
    )),
]

_classes = [
    MINIATURE_OT_set_origin,
    MINIATURE_OT_set_origin_multipart,
    MINIATURE_PT_panel,
]


def register():
    for name, prop in _scene_props:
        setattr(bpy.types.Scene, name, prop)
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
    for name, _ in _scene_props:
        if hasattr(bpy.types.Scene, name):
            delattr(bpy.types.Scene, name)


if __name__ == "__main__":
    register()
