bl_info = {
    "name": "Miniature Origin Setter",
    "author": "philipischneider",
    "version": (1, 5, 1),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Miniature",
    "description": (
        "Reposiciona automaticamente a origem de miniaturas STL para o centroide "
        "da superfície inferior, depois move o objeto para a origem do mundo (0,0,0)."
    ),
    "category": "Object",
}

import math

import bpy
import bmesh
from mathutils import Matrix, Vector


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
# Base bounding-box helper
# ---------------------------------------------------------------------------

def get_base_extent_1d(obj, base_height, axis):
    """
    Retorna (min, max) em espaço mundo ao longo de `axis` ('X' ou 'Y'),
    considerando apenas os vértices que estão dentro de `base_height` acima
    do limite inferior do mesh.

    Usado para calcular o bounding box da BASE da miniatura, ignorando braços,
    armas ou qualquer geometria acima da altura informada.
    """
    mesh = obj.data
    matrix = obj.matrix_world

    world_verts = [(matrix @ v.co) for v in mesh.vertices]
    if not world_verts:
        return None

    min_z = min(v.z for v in world_verts)
    threshold = min_z + base_height

    base_verts = [v for v in world_verts if v.z <= threshold]
    if not base_verts:
        base_verts = world_verts

    if axis == 'X':
        values = [v.x for v in base_verts]
    else:
        values = [v.y for v in base_verts]

    return (min(values), max(values))


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
# Operator – distribuição horizontal
# ---------------------------------------------------------------------------

class MINIATURE_OT_distribute(bpy.types.Operator):
    """
    Distribui os meshes selecionados ao longo de um eixo horizontal.
    O espaçamento é calculado a partir do bounding box da BASE de cada miniatura
    (vértices dentro de `base_height` acima do limite inferior), não do mesh inteiro.
    A distância configurada é entre os limites dos bounding boxes, não entre origens.
    """
    bl_idname = "miniature.distribute"
    bl_label = "Distribuir Miniaturas"
    bl_options = {'REGISTER', 'UNDO'}

    base_height: bpy.props.FloatProperty(
        name="Altura da Base",
        description=(
            "Altura a partir do limite inferior do mesh considerada para calcular "
            "o bounding box da base. Vértices acima deste valor são ignorados."
        ),
        default=5.0,
        min=0.0001,
        soft_max=50.0,
        precision=3,
        unit='LENGTH',
    )

    axis: bpy.props.EnumProperty(
        name="Eixo",
        description="Eixo ao longo do qual as miniaturas serão distribuídas",
        items=[
            ('X', "X", "Distribuir ao longo do eixo X"),
            ('Y', "Y", "Distribuir ao longo do eixo Y"),
        ],
        default='X',
    )

    gap: bpy.props.FloatProperty(
        name="Espaçamento",
        description="Distância entre os limites dos bounding boxes de bases adjacentes",
        default=5.0,
        min=0.0,
        soft_max=100.0,
        precision=3,
        unit='LENGTH',
    )

    start_pos: bpy.props.FloatProperty(
        name="Posição Inicial",
        description=(
            "Posição no eixo escolhido onde o limite inferior do bounding box "
            "da primeira miniatura será colocado"
        ),
        default=0.0,
        precision=3,
        unit='LENGTH',
    )

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        targets = [o for o in context.selected_objects if o.type == 'MESH']
        if len(targets) < 2:
            self.report({'ERROR'}, "Selecione pelo menos 2 meshes para distribuir.")
            return {'CANCELLED'}

        if self.axis == 'XY':
            self.report({'ERROR'}, "Distribuir requer um único eixo (X ou Y). Use X+Y apenas para Centralizar.")
            return {'CANCELLED'}

        # Garantir que matrix_world está atualizado antes de qualquer leitura de vértices.
        # O Blender avalia o depsgraph de forma lazy; sem isso, objetos movidos pelo
        # operador anterior ainda teriam matrix_world desatualizados.
        context.view_layer.update()

        # ── Fase 1: calcular todos os extents ANTES de mover qualquer objeto ──────
        # Armazena: bbox_min, bbox_max (espaço mundo) e world_origin no eixo.
        # Capturar world_origin via matrix_world.translation é mais robusto do que
        # obj.location quando o objeto tem parent ou escala não-aplicada.
        data = {}
        for obj in targets:
            ext = get_base_extent_1d(obj, self.base_height, self.axis)
            if ext is None:
                self.report({'WARNING'}, f"'{obj.name}': mesh vazio, ignorado.")
                continue
            axis_idx = 0 if self.axis == 'X' else 1
            world_origin = obj.matrix_world.translation[axis_idx]
            data[obj.name] = {
                'obj': obj,
                'bbox_min': ext[0],
                'bbox_max': ext[1],
                'width': ext[1] - ext[0],
                # offset estrutural: distância fixa entre a origem e o bbox_min,
                # independente de onde o objeto estiver posicionado.
                'offset': ext[0] - world_origin,
            }

        if not data:
            self.report({'ERROR'}, "Nenhum objeto válido para distribuir.")
            return {'CANCELLED'}

        # ── Fase 2: ordenar pelo bbox_min atual (mais intuitivo que por origin) ──
        sorted_data = sorted(data.values(), key=lambda d: d['bbox_min'])

        # ── Fase 3: posicionar — apenas leitura de 'offset' e 'width', sem reuso ─
        # Para cada objeto, queremos:   new_bbox_min = current_edge
        # Sabemos que:                  new_bbox_min = new_world_origin + offset
        # Logo:                         new_world_origin = current_edge - offset
        #
        # Para objetos sem parent: world_origin == obj.location[ax], então basta
        # atribuir diretamente.  Com parent, convertemos via diferença de delta.
        current_edge = self.start_pos
        placed = 0

        for d in sorted_data:
            obj = d['obj']
            axis_idx = 0 if self.axis == 'X' else 1

            new_world_origin = current_edge - d['offset']
            # Calcular o delta em espaço mundo e aplicar à location local.
            # Isso funciona com ou sem parent, com qualquer escala/rotação.
            current_world_origin = obj.matrix_world.translation[axis_idx]
            delta = new_world_origin - current_world_origin
            obj.location[axis_idx] += delta

            current_edge += d['width'] + self.gap
            placed += 1

        self.report({'INFO'}, f"{placed} miniatura(s) distribuída(s) ao longo de {self.axis}.")
        return {'FINISHED'}

    def invoke(self, context, event):
        scene = context.scene
        self.base_height = scene.miniature_base_height
        self.axis = scene.miniature_distribute_axis
        self.gap = scene.miniature_distribute_gap
        self.start_pos = scene.miniature_distribute_start
        return self.execute(context)


# ---------------------------------------------------------------------------
# Operator – centralizar conjunto na origem do mundo
# ---------------------------------------------------------------------------

class MINIATURE_OT_center_at_origin(bpy.types.Operator):
    """
    Move todos os meshes selecionados de forma que o centro do bounding box
    combinado de suas bases fique em 0 no eixo escolhido.
    Todos os objetos se deslocam pelo mesmo delta, preservando posições relativas.
    """
    bl_idname = "miniature.center_at_origin"
    bl_label = "Centralizar na Origem"
    bl_options = {'REGISTER', 'UNDO'}

    base_height: bpy.props.FloatProperty(
        name="Altura da Base",
        description=(
            "Altura a partir do limite inferior considerada para calcular "
            "o bounding box da base."
        ),
        default=5.0,
        min=0.0001,
        soft_max=50.0,
        precision=3,
        unit='LENGTH',
    )

    axis: bpy.props.EnumProperty(
        name="Eixo",
        description="Eixo no qual o conjunto será centralizado em 0",
        items=[
            ('X', "X", "Centralizar ao longo do eixo X"),
            ('Y', "Y", "Centralizar ao longo do eixo Y"),
            ('XY', "X e Y", "Centralizar em ambos os eixos simultaneamente"),
        ],
        default='X',
    )

    def execute(self, context):
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')

        targets = [o for o in context.selected_objects if o.type == 'MESH']
        if not targets:
            self.report({'ERROR'}, "Nenhum mesh selecionado.")
            return {'CANCELLED'}

        context.view_layer.update()

        axes = ['X', 'Y'] if self.axis == 'XY' else [self.axis]

        for ax in axes:
            axis_idx = 0 if ax == 'X' else 1

            # Calcular o bounding box combinado de todas as bases no eixo
            global_min = float('inf')
            global_max = float('-inf')

            valid_objects = []
            for obj in targets:
                ext = get_base_extent_1d(obj, self.base_height, ax)
                if ext is None:
                    continue
                global_min = min(global_min, ext[0])
                global_max = max(global_max, ext[1])
                valid_objects.append(obj)

            if not valid_objects:
                continue

            # Delta para que o centro do conjunto fique em 0
            center = (global_min + global_max) / 2.0
            delta = -center

            for obj in valid_objects:
                obj.location[axis_idx] += delta

        self.report({'INFO'}, f"Conjunto centralizado em {self.axis} = 0.")
        return {'FINISHED'}

    def invoke(self, context, _event):
        scene = context.scene
        self.base_height = scene.miniature_base_height
        self.axis = scene.miniature_distribute_axis
        return self.execute(context)


# ---------------------------------------------------------------------------
# Operator – enquadrar câmera
# ---------------------------------------------------------------------------

class MINIATURE_OT_frame_camera(bpy.types.Operator):
    """
    Posiciona a câmera ativa para que as miniaturas selecionadas ocupem a
    porcentagem especificada da largura horizontal da imagem.
    A orientação da câmera é preservada; apenas a posição (location) é alterada.
    """
    bl_idname = "miniature.frame_camera"
    bl_label = "Enquadrar Câmera"
    bl_options = {'REGISTER', 'UNDO'}

    fill_percent: bpy.props.FloatProperty(
        name="Preenchimento Horizontal",
        description=(
            "Porcentagem da largura da imagem que as miniaturas devem ocupar. "
            "Ex.: 80 → as miniaturas ocupam 80 % da largura do frame."
        ),
        default=80.0,
        min=1.0,
        max=99.0,
        precision=1,
        subtype='PERCENTAGE',
    )

    view_axis: bpy.props.EnumProperty(
        name="Eixo / Lado",
        description="Lado a partir do qual a câmera verá as miniaturas",
        items=[
            ('X_POS', "+X", "Câmera no lado +X, olhando para -X"),
            ('X_NEG', "-X", "Câmera no lado -X, olhando para +X"),
            ('Y_POS', "+Y", "Câmera no lado +Y, olhando para -Y"),
            ('Y_NEG', "-Y", "Câmera no lado -Y, olhando para +Y"),
        ],
        default='Y_NEG',
    )

    def execute(self, context):
        camera = context.scene.camera
        if camera is None or camera.type != 'CAMERA':
            self.report({'ERROR'}, "Nenhuma câmera ativa na cena.")
            return {'CANCELLED'}

        if camera.data.type == 'ORTHO':
            self.report({'ERROR'}, "Câmera ortográfica não é suportada.")
            return {'CANCELLED'}

        targets = [o for o in context.selected_objects if o.type == 'MESH']
        if not targets:
            self.report({'ERROR'}, "Nenhum mesh selecionado.")
            return {'CANCELLED'}

        context.view_layer.update()

        # 1. Bounding box 3D unificado de todos os meshes (espaço mundo)
        all_verts = []
        for obj in targets:
            m = obj.matrix_world
            for v in obj.data.vertices:
                all_verts.append(m @ v.co)

        if not all_verts:
            self.report({'ERROR'}, "Meshes sem vértices.")
            return {'CANCELLED'}

        xs = [v.x for v in all_verts]
        ys = [v.y for v in all_verts]
        zs = [v.z for v in all_verts]

        bbox_center = Vector((
            (min(xs) + max(xs)) / 2.0,
            (min(ys) + max(ys)) / 2.0,
            (min(zs) + max(zs)) / 2.0,
        ))

        corners = [
            Vector((x, y, z))
            for x in (min(xs), max(xs))
            for y in (min(ys), max(ys))
            for z in (min(zs), max(zs))
        ]

        # 2. Direção de visão → sistema de coordenadas da câmera
        #
        # look_dir  : direção de câmera → alvo (normalizada)
        # cam_z     = -look_dir          (câmera aponta ao longo de -Z local)
        # cam_x     = normalize(look_dir × world_up)   (eixo horizontal, à direita)
        # cam_y     = normalize(cam_z × cam_x)          (eixo vertical, sempre = world +Z
        #                                                 para vistas puramente laterais)
        #
        # A matriz de rotação tem cam_x, cam_y, cam_z como COLUNAS
        # (eixos locais expressos em espaço mundo).

        look_dirs = {
            'X_POS': Vector((-1.0,  0.0, 0.0)),
            'X_NEG': Vector(( 1.0,  0.0, 0.0)),
            'Y_POS': Vector(( 0.0, -1.0, 0.0)),
            'Y_NEG': Vector(( 0.0,  1.0, 0.0)),
        }
        look_dir  = look_dirs[self.view_axis]
        world_up  = Vector((0.0, 0.0, 1.0))

        cam_z = -look_dir
        cam_x = look_dir.cross(world_up).normalized()
        cam_y = cam_z.cross(cam_x).normalized()

        # 3. FOV horizontal
        cam_data = camera.data
        render   = context.scene.render
        aspect   = render.resolution_x / render.resolution_y
        sw, sh, fl = cam_data.sensor_width, cam_data.sensor_height, cam_data.lens

        if cam_data.sensor_fit == 'VERTICAL':
            eff_sw = sh * aspect
        elif cam_data.sensor_fit == 'AUTO':
            eff_sw = sw if aspect >= 1.0 else sh * aspect
        else:
            eff_sw = sw

        h_fov = 2.0 * math.atan(eff_sw / (2.0 * fl))

        # 4. Verificar extensão horizontal mínima
        right_vals = [c.dot(cam_x) for c in corners]
        half_w = (max(right_vals) - min(right_vals)) / 2.0

        if half_w < 1e-9:
            self.report({'ERROR'}, "Bounding box com largura zero na direção da câmera.")
            return {'CANCELLED'}

        # 5. Distância corrigida para perspectiva
        #
        # A fórmula ingênua  D = half_w / (fill·tan(h_fov/2))  supõe que todos os
        # cantos estão à mesma profundidade D.  Na prática os cantos da face mais
        # próxima da câmera estão a D − Δ e projetam um ângulo MAIOR que o calculado,
        # fazendo as miniaturas aparecerem cortadas (especialmente grave quando a
        # extensão ao longo do eixo de visão é grande, como em vistas X com objetos
        # distribuídos em X).
        #
        # Derivação por canto:
        #   profundidade do canto c = D + (c − bbox_center)·look_dir
        #   ângulo horizontal       = |cam_x·(c − bbox_center)| / profundidade_c
        #   para fill:  D ≥ |right_c| / f  −  (c − bbox_center)·look_dir
        #
        # O D mínimo que enquadra todos os cantos é o máximo sobre os 8 cantos.
        fill = self.fill_percent / 100.0
        f    = fill * math.tan(h_fov / 2.0)

        D = max(
            abs((c - bbox_center).dot(cam_x)) / f - (c - bbox_center).dot(look_dir)
            for c in corners
        )

        # 6. Posição: bbox_center recuado D unidades ao longo de look_dir
        camera.location = bbox_center - look_dir * D

        # 7. Rotação: matriz com cam_x, cam_y, cam_z como colunas
        rot_mat = Matrix((cam_x, cam_y, cam_z)).transposed()
        mode = camera.rotation_mode
        if mode == 'QUATERNION':
            camera.rotation_quaternion = rot_mat.to_quaternion()
        elif mode == 'AXIS_ANGLE':
            axis, angle = rot_mat.to_quaternion().to_axis_angle()
            camera.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
        else:
            camera.rotation_euler = rot_mat.to_euler(mode)

        self.report(
            {'INFO'},
            f"Câmera {self.view_axis} | D: {D:.3f} u | FOV H: {math.degrees(h_fov):.1f}° | Fill: {self.fill_percent:.0f}%"
        )
        return {'FINISHED'}

    def invoke(self, context, _event):
        scene = context.scene
        self.fill_percent = scene.miniature_camera_fill
        self.view_axis    = scene.miniature_camera_axis
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

        # ── Seção: Distribuição ──────────────────────────────────────────────
        box_dist = layout.box()
        box_dist.label(text="Distribuir Miniaturas", icon='SORTSIZE')

        col = box_dist.column(align=True)
        col.prop(scene, "miniature_base_height")
        col.prop(scene, "miniature_distribute_gap")
        col.prop(scene, "miniature_distribute_start")

        box_dist.prop(scene, "miniature_distribute_axis", expand=True)

        # Distribuir só faz sentido em um único eixo — desabilitar quando XY
        dist_axis = scene.miniature_distribute_axis
        row = box_dist.row()
        row.scale_y = 1.4
        row.enabled = dist_axis != 'XY'
        op_dist = row.operator("miniature.distribute", icon='SNAP_INCREMENT')
        op_dist.base_height = scene.miniature_base_height
        op_dist.axis = dist_axis if dist_axis != 'XY' else 'X'  # nunca passa 'XY' ao enum
        op_dist.gap = scene.miniature_distribute_gap
        op_dist.start_pos = scene.miniature_distribute_start

        row2 = box_dist.row()
        row2.scale_y = 1.4
        op_ctr = row2.operator("miniature.center_at_origin", icon='PIVOT_CURSOR')
        op_ctr.base_height = scene.miniature_base_height
        op_ctr.axis = dist_axis

        layout.separator()

        # ── Seção: Câmera ────────────────────────────────────────────────────
        box_cam = layout.box()
        box_cam.label(text="Enquadrar Câmera", icon='CAMERA_DATA')

        cam = context.scene.camera
        if cam:
            box_cam.label(text=f"Câmera ativa: {cam.name}", icon='CHECKMARK')
        else:
            box_cam.label(text="Sem câmera ativa na cena", icon='ERROR')

        box_cam.prop(scene, "miniature_camera_fill")
        box_cam.prop(scene, "miniature_camera_axis", expand=True)

        row_cam = box_cam.row()
        row_cam.scale_y = 1.4
        row_cam.enabled = cam is not None
        op_cam = row_cam.operator("miniature.frame_camera", icon='CAMERA_DATA')
        op_cam.fill_percent = scene.miniature_camera_fill
        op_cam.view_axis   = scene.miniature_camera_axis

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
    ("miniature_base_height", bpy.props.FloatProperty(
        name="Altura da Base",
        description=(
            "Altura a partir do limite inferior considerada para calcular o "
            "bounding box da base. Vértices acima deste valor são ignorados."
        ),
        default=5.0,
        min=0.0001,
        soft_max=50.0,
        precision=3,
        unit='LENGTH',
    )),
    ("miniature_distribute_axis", bpy.props.EnumProperty(
        name="Eixo",
        description="Eixo para distribuição e centralização",
        items=[
            ('X',  "X",    "Eixo X"),
            ('Y',  "Y",    "Eixo Y"),
            ('XY', "X+Y",  "Ambos os eixos (só para centralizar)"),
        ],
        default='X',
    )),
    ("miniature_distribute_gap", bpy.props.FloatProperty(
        name="Espaçamento",
        description="Distância entre os limites dos bounding boxes de bases adjacentes",
        default=5.0,
        min=0.0,
        soft_max=100.0,
        precision=3,
        unit='LENGTH',
    )),
    ("miniature_distribute_start", bpy.props.FloatProperty(
        name="Posição Inicial",
        description=(
            "Posição no eixo escolhido onde o limite do bounding box "
            "da primeira miniatura será colocado"
        ),
        default=0.0,
        precision=3,
        unit='LENGTH',
    )),
    ("miniature_camera_fill", bpy.props.FloatProperty(
        name="Preenchimento Horizontal",
        description=(
            "Porcentagem da largura da imagem que as miniaturas devem ocupar. "
            "Ex.: 80 → as miniaturas ocupam 80 % da largura do frame."
        ),
        default=80.0,
        min=1.0,
        max=99.0,
        precision=1,
        subtype='PERCENTAGE',
    )),
    ("miniature_camera_axis", bpy.props.EnumProperty(
        name="Eixo / Lado",
        description="Lado a partir do qual a câmera verá as miniaturas",
        items=[
            ('X_POS', "+X", "Câmera no lado +X, olhando para -X"),
            ('X_NEG', "-X", "Câmera no lado -X, olhando para +X"),
            ('Y_POS', "+Y", "Câmera no lado +Y, olhando para -Y"),
            ('Y_NEG', "-Y", "Câmera no lado -Y, olhando para +Y"),
        ],
        default='Y_NEG',
    )),
]

_classes = [
    MINIATURE_OT_set_origin,
    MINIATURE_OT_set_origin_multipart,
    MINIATURE_OT_distribute,
    MINIATURE_OT_center_at_origin,
    MINIATURE_OT_frame_camera,
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
