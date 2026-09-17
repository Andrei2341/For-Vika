bl_info = {
    "name": "LowPoly Palette Master",
    "author": "OpenAI",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar > LowPoly Master",
    "description": "Generate stylized Low Poly palettes and apply them to selected mesh faces.",
    "category": "3D View",
}

import colorsys

import bmesh
import bpy
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty, PointerProperty
from bpy.types import Operator, Panel, PropertyGroup


# -----------------------------------------------------------------------------
# Константы аддона
# -----------------------------------------------------------------------------

MATERIAL_NAME = "LowPoly_Material"
COLOR_ATTRIBUTE_NAME = "LowPoly_Palette_Color"

PRESET_BRIGHT = "BRIGHT_CARTOON"
PRESET_PASTEL = "PASTEL_COZY"
PRESET_FANTASY = "FANTASY_RICH"

PRESET_ITEMS = (
    (
        PRESET_BRIGHT,
        "Low Poly (Bright / Cartoon)",
        "Juicy cartoon colors: lively shadows, clean highlights, roughness 0.4",
    ),
    (
        PRESET_PASTEL,
        "Low Poly (Pastel / Cozy)",
        "Soft low-contrast pastel colors with raised value, roughness 0.6",
    ),
    (
        PRESET_FANTASY,
        "Low Poly (Fantasy / Rich)",
        "Deep painterly shadows with rich saturation, roughness 0.8",
    ),
)


# -----------------------------------------------------------------------------
# Математический движок палитры
# -----------------------------------------------------------------------------

def clamp01(value):
    """Ограничивает любое числовое значение диапазоном RGB/HSV 0..1."""
    return max(0.0, min(1.0, float(value)))


def rgb_to_safe_tuple(color):
    """Берет первые три канала цвета и гарантирует корректный RGB-кортеж."""
    return tuple(clamp01(channel) for channel in color[:3])


def shift_hue(hue, degrees, intensity):
    """Сдвигает hue по кругу HSV, где hue хранится в диапазоне 0..1."""
    return (hue + (degrees * intensity / 360.0)) % 1.0


def scale_saturation(saturation, multiplier):
    """Мягко усиливает или приглушает насыщенность."""
    return clamp01(saturation * multiplier)


def scale_value(value, multiplier):
    """Мягко затемняет или осветляет value-канал HSV."""
    return clamp01(value * multiplier)


def lift_value(value, amount):
    """Поднимает value к белому, не выбивая канал за пределы 1.0."""
    return clamp01(value + (1.0 - value) * amount)


def hsv_to_rgb_tuple(hue, saturation, value):
    """Возвращает RGB-кортеж из HSV с финальным clamp для надежности."""
    return tuple(clamp01(channel) for channel in colorsys.hsv_to_rgb(hue, saturation, value))


def calculate_lowpoly_palette(base_color_rgb, preset, intensity):
    """Рассчитывает Shadow / Base / Highlight и Roughness для выбранного стиля.

    Parameters
    ----------
    base_color_rgb : sequence[float]
        Базовый цвет в RGB. Ожидаются значения 0..1; лишние каналы игнорируются.
    preset : str
        Один из идентификаторов PRESET_BRIGHT / PRESET_PASTEL / PRESET_FANTASY.
    intensity : float
        Сила именно hue-сдвига. Значение 1.0 соответствует указанным в ТЗ градусам.

    Returns
    -------
    dict
        {
            "shadow": (r, g, b),
            "base": (r, g, b),
            "highlight": (r, g, b),
            "roughness": float,
        }
    """
    base_rgb = rgb_to_safe_tuple(base_color_rgb)
    hue, saturation, value = colorsys.rgb_to_hsv(*base_rgb)
    intensity = max(0.0, min(2.0, float(intensity)))

    if preset == PRESET_PASTEL:
        # Pastel / Cozy: сначала пастелизируем базу, затем строим низкий контраст.
        base_hue = hue
        base_saturation = scale_saturation(saturation, 0.85)  # Saturation -15%
        base_value = lift_value(value, 0.10)  # Value +10% к белому

        shadow = hsv_to_rgb_tuple(
            shift_hue(base_hue, -5.0, intensity),
            scale_saturation(base_saturation, 0.95),
            scale_value(base_value, 0.82),
        )
        base = hsv_to_rgb_tuple(base_hue, base_saturation, base_value)
        highlight = hsv_to_rgb_tuple(
            shift_hue(base_hue, 3.0, intensity),
            scale_saturation(base_saturation, 0.90),
            lift_value(base_value, 0.18),
        )
        roughness = 0.6

    elif preset == PRESET_FANTASY:
        # Fantasy / Rich: глубокая сине-фиолетовая тень и более живописный свет.
        shadow = hsv_to_rgb_tuple(
            shift_hue(hue, -25.0, intensity),
            scale_saturation(saturation, 1.25),  # Saturation +25% в тени
            scale_value(value, 0.52),
        )
        base = hsv_to_rgb_tuple(
            hue,
            scale_saturation(saturation, 1.05),
            scale_value(value, 0.92),
        )
        highlight = hsv_to_rgb_tuple(
            shift_hue(hue, 10.0, intensity),
            scale_saturation(saturation, 0.98),
            lift_value(value, 0.38),
        )
        roughness = 0.8

    else:
        # Bright / Cartoon: сочная тень и чистый теплый/светлый блик.
        shadow = hsv_to_rgb_tuple(
            shift_hue(hue, -10.0, intensity),
            scale_saturation(saturation, 1.15),  # Saturation +15% в тени
            scale_value(value, 0.68),
        )
        base = base_rgb
        highlight = hsv_to_rgb_tuple(
            shift_hue(hue, 5.0, intensity),
            saturation,
            lift_value(value, 0.42),
        )
        roughness = 0.4

    return {
        "shadow": shadow,
        "base": base,
        "highlight": highlight,
        "roughness": roughness,
    }


def rgb_to_rgba(rgb, alpha=1.0):
    """Добавляет alpha-канал к RGB для Blender RNA и нодовых цветов."""
    return (clamp01(rgb[0]), clamp01(rgb[1]), clamp01(rgb[2]), clamp01(alpha))


def lerp_rgb(color_a, color_b, factor):
    """Линейная интерполяция двух RGB-цветов."""
    factor = clamp01(factor)
    return tuple(color_a[index] + (color_b[index] - color_a[index]) * factor for index in range(3))


def sample_three_stop_palette(shadow, base, highlight, factor):
    """Берет цвет из трехточечной палитры: 0=Shadow, 0.5=Base, 1=Highlight."""
    factor = clamp01(factor)
    if factor <= 0.5:
        return lerp_rgb(shadow, base, factor * 2.0)
    return lerp_rgb(base, highlight, (factor - 0.5) * 2.0)


# -----------------------------------------------------------------------------
# Динамические preview-поля для N-панели
# -----------------------------------------------------------------------------

def preview_color(settings, key):
    """Вычисляет один preview-цвет без записи скрытых данных в сцену."""
    try:
        palette = calculate_lowpoly_palette(
            settings.base_color[:3],
            settings.preset,
            settings.hue_shift_intensity,
        )
        return rgb_to_rgba(palette[key], settings.base_color[3])
    except Exception:
        # UI draw не должен падать из-за временно некорректного состояния RNA.
        return (0.0, 0.0, 0.0, 1.0)


def preview_shadow_get(settings):
    return preview_color(settings, "shadow")


def preview_base_get(settings):
    return preview_color(settings, "base")


def preview_highlight_get(settings):
    return preview_color(settings, "highlight")


class LOWPOLY_PaletteSettings(PropertyGroup):
    """Настройки палитры, доступные пользователю в N-панели."""

    base_color: FloatVectorProperty(
        name="Base Color",
        description="Main color of the selected detail",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        default=(0.95, 0.35, 0.12, 1.0),
    )

    preset: EnumProperty(
        name="Low Poly Preset",
        description="Palette style preset",
        items=PRESET_ITEMS,
        default=PRESET_BRIGHT,
    )

    hue_shift_intensity: FloatProperty(
        name="Hue Shift Intensity",
        description="Strength multiplier for hue shifts in the selected preset",
        min=0.0,
        max=2.0,
        default=1.0,
        subtype="FACTOR",
    )

    preview_shadow: FloatVectorProperty(
        name="Shadow",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        get=preview_shadow_get,
    )

    preview_base: FloatVectorProperty(
        name="Base",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        get=preview_base_get,
    )

    preview_highlight: FloatVectorProperty(
        name="Highlight",
        subtype="COLOR",
        size=4,
        min=0.0,
        max=1.0,
        get=preview_highlight_get,
    )


# -----------------------------------------------------------------------------
# Проверки контекста
# -----------------------------------------------------------------------------

def validate_edit_mesh_context(context, operator):
    """Проверяет активный объект и возвращает Mesh-объект либо None."""
    obj = context.object

    if obj is None:
        operator.report({"WARNING"}, "No active object. Select a mesh object first.")
        return None

    if obj.type != "MESH":
        operator.report({"WARNING"}, "Active object is not a Mesh.")
        return None

    if context.mode != "EDIT_MESH" or obj.mode != "EDIT":
        operator.report({"WARNING"}, "Switch the mesh to Edit Mode and select faces.")
        return None

    return obj


def selected_bmesh_faces(mesh, operator):
    """Возвращает bmesh и список выделенных граней текущего edit mesh."""
    bm = bmesh.from_edit_mesh(mesh)
    bm.faces.ensure_lookup_table()
    faces = [face for face in bm.faces if face.select]

    if not faces:
        operator.report({"WARNING"}, "No selected faces found.")
        return bm, []

    return bm, faces


# -----------------------------------------------------------------------------
# Материалы и node tree
# -----------------------------------------------------------------------------

def get_first_node_by_type(nodes, bl_idname):
    """Ищет первую ноду указанного типа в node tree."""
    for node in nodes:
        if node.bl_idname == bl_idname:
            return node
    return None


def get_or_create_material_slot(obj, material):
    """Находит или добавляет материал в слотах объекта и возвращает индекс слота."""
    for index, slot_material in enumerate(obj.data.materials):
        if slot_material == material or (slot_material and slot_material.name == material.name):
            return index

    obj.data.materials.append(material)
    return len(obj.data.materials) - 1


def ensure_lowpoly_material():
    """Создает или возвращает материал, которым аддон красит выделенные faces."""
    material = bpy.data.materials.get(MATERIAL_NAME)
    if material is None:
        material = bpy.data.materials.new(MATERIAL_NAME)

    material.use_nodes = True
    return material


def ensure_socket_link(node_tree, output_socket, input_socket):
    """Подключает socket, предварительно убирая старые входящие связи."""
    for link in list(input_socket.links):
        node_tree.links.remove(link)
    node_tree.links.new(output_socket, input_socket)


def configure_color_ramp(ramp_node, palette, alpha):
    """Гарантирует три stop'а ColorRamp: Shadow, Base и Highlight."""
    color_ramp = ramp_node.color_ramp

    # CONSTANT сохраняет low-poly характер: ramp ведет себя как набор плоских тонов.
    color_ramp.interpolation = "CONSTANT"

    # У ColorRamp всегда минимум два элемента; лишние убираем, затем добавляем середину.
    while len(color_ramp.elements) > 2:
        color_ramp.elements.remove(color_ramp.elements[len(color_ramp.elements) - 1])

    color_ramp.elements[0].position = 0.0
    color_ramp.elements[1].position = 1.0
    middle = color_ramp.elements.new(0.5)

    elements = sorted(color_ramp.elements, key=lambda element: element.position)
    elements[0].color = rgb_to_rgba(palette["shadow"], alpha)
    elements[1].color = rgb_to_rgba(palette["base"], alpha)
    elements[2].color = rgb_to_rgba(palette["highlight"], alpha)


def configure_lowpoly_material(material, palette, alpha):
    """Настраивает Principled BSDF + ColorRamp для LowPoly_Material."""
    material.diffuse_color = rgb_to_rgba(palette["base"], alpha)
    material.use_nodes = True

    node_tree = material.node_tree
    nodes = node_tree.nodes

    output_node = get_first_node_by_type(nodes, "ShaderNodeOutputMaterial")
    if output_node is None:
        output_node = nodes.new("ShaderNodeOutputMaterial")
        output_node.location = (320, 80)

    bsdf_node = get_first_node_by_type(nodes, "ShaderNodeBsdfPrincipled")
    if bsdf_node is None:
        bsdf_node = nodes.new("ShaderNodeBsdfPrincipled")
    bsdf_node.name = "LowPoly Principled BSDF"
    bsdf_node.label = "LowPoly Principled BSDF"
    bsdf_node.location = (40, 80)

    ramp_node = None
    for node in nodes:
        if node.bl_idname == "ShaderNodeValToRGB" and node.name == "LowPoly ColorRamp":
            ramp_node = node
            break
    if ramp_node is None:
        ramp_node = nodes.new("ShaderNodeValToRGB")
    ramp_node.name = "LowPoly ColorRamp"
    ramp_node.label = "LowPoly Palette"
    ramp_node.location = (-260, 80)

    configure_color_ramp(ramp_node, palette, alpha)

    # Без входящего Fac ColorRamp выдает центральный тон; пользователь может позже
    # подключить сюда procedural mask/noise и уже получит готовые Shadow/Base/Highlight.
    if "Fac" in ramp_node.inputs:
        ramp_node.inputs["Fac"].default_value = 0.5

    base_color_input = bsdf_node.inputs.get("Base Color")
    roughness_input = bsdf_node.inputs.get("Roughness")
    surface_input = output_node.inputs.get("Surface")

    if base_color_input is not None:
        ensure_socket_link(node_tree, ramp_node.outputs["Color"], base_color_input)
    if roughness_input is not None:
        roughness_input.default_value = palette["roughness"]
    if surface_input is not None:
        ensure_socket_link(node_tree, bsdf_node.outputs["BSDF"], surface_input)


# -----------------------------------------------------------------------------
# Color Attributes / Vertex Colors
# -----------------------------------------------------------------------------

def ensure_bmesh_color_layer(bm):
    """Создает float color attribute на face-corner domain для edit bmesh."""
    layer_collection = bm.loops.layers.float_color
    color_layer = layer_collection.get(COLOR_ATTRIBUTE_NAME)
    if color_layer is None:
        color_layer = layer_collection.new(COLOR_ATTRIBUTE_NAME)
    return color_layer


def set_loop_color(loop, color_layer, rgba):
    """Записывает цвет в bmesh loop layer с учетом разных представлений API."""
    try:
        loop[color_layer] = rgba
    except TypeError:
        # В некоторых сборках Blender элемент слоя возвращает объект с .color.
        loop[color_layer].color = rgba


def set_active_color_attribute(mesh):
    """Делает созданный color attribute активным, если Blender API это позволяет."""
    color_attribute = mesh.color_attributes.get(COLOR_ATTRIBUTE_NAME)
    if color_attribute is None:
        return

    # В Blender 4.x активный color attribute хранится на AttributeGroup.
    try:
        mesh.attributes.active_color = color_attribute
    except Exception:
        pass

    # Дополнительная попытка для сборок, где доступен активный индекс.
    try:
        for index, attribute in enumerate(mesh.color_attributes):
            if attribute.name == COLOR_ATTRIBUTE_NAME:
                mesh.attributes.active_color_index = index
                break
    except Exception:
        pass


# -----------------------------------------------------------------------------
# Операторы
# -----------------------------------------------------------------------------

class LOWPOLY_OT_apply_palette_to_faces(Operator):
    """Apply the generated material palette to selected mesh faces."""

    bl_idname = "lowpoly_master.apply_palette_to_faces"
    bl_label = "Apply Palette to Selected Faces"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = validate_edit_mesh_context(context, self)
        if obj is None:
            return {"CANCELLED"}

        bm, faces = selected_bmesh_faces(obj.data, self)
        if not faces:
            return {"CANCELLED"}

        settings = context.scene.lowpoly_palette_master
        palette = calculate_lowpoly_palette(
            settings.base_color[:3],
            settings.preset,
            settings.hue_shift_intensity,
        )

        material = ensure_lowpoly_material()
        configure_lowpoly_material(material, palette, settings.base_color[3])
        material_index = get_or_create_material_slot(obj, material)

        for face in faces:
            face.material_index = material_index

        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)

        self.report(
            {"INFO"},
            f"Applied LowPoly_Material to {len(faces)} selected face(s).",
        )
        return {"FINISHED"}


class LOWPOLY_OT_apply_to_vertex_colors(Operator):
    """Paint selected faces into a Color Attribute using the generated palette."""

    bl_idname = "lowpoly_master.apply_to_vertex_colors"
    bl_label = "Apply to Vertex Colors"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        obj = validate_edit_mesh_context(context, self)
        if obj is None:
            return {"CANCELLED"}

        bm, faces = selected_bmesh_faces(obj.data, self)
        if not faces:
            return {"CANCELLED"}

        settings = context.scene.lowpoly_palette_master
        palette = calculate_lowpoly_palette(
            settings.base_color[:3],
            settings.preset,
            settings.hue_shift_intensity,
        )

        color_layer = ensure_bmesh_color_layer(bm)
        alpha = settings.base_color[3]

        # Градиент строим по мировой Z-координате, чтобы "нижнее/верхнее" совпадало
        # с тем, как художник видит объект в сцене.
        z_values = [
            (obj.matrix_world @ loop.vert.co).z
            for face in faces
            for loop in face.loops
        ]
        min_z = min(z_values)
        max_z = max(z_values)
        z_range = max_z - min_z

        for face in faces:
            for loop in face.loops:
                if z_range <= 0.000001:
                    factor = 0.5
                else:
                    factor = ((obj.matrix_world @ loop.vert.co).z - min_z) / z_range

                rgb = sample_three_stop_palette(
                    palette["shadow"],
                    palette["base"],
                    palette["highlight"],
                    factor,
                )
                set_loop_color(loop, color_layer, rgb_to_rgba(rgb, alpha))

        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        set_active_color_attribute(obj.data)

        self.report(
            {"INFO"},
            f"Painted {len(faces)} selected face(s) into Color Attribute '{COLOR_ATTRIBUTE_NAME}'.",
        )
        return {"FINISHED"}


# -----------------------------------------------------------------------------
# N-panel UI
# -----------------------------------------------------------------------------

class LOWPOLY_PT_palette_master(Panel):
    """N-панель аддона во Viewport sidebar."""

    bl_label = "LowPoly Palette Master"
    bl_idname = "LOWPOLY_PT_palette_master"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "LowPoly Master"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.lowpoly_palette_master

        palette = calculate_lowpoly_palette(
            settings.base_color[:3],
            settings.preset,
            settings.hue_shift_intensity,
        )

        settings_box = layout.box()
        settings_box.label(text="Palette Settings")
        settings_box.prop(settings, "base_color", text="Base Color")
        settings_box.prop(settings, "preset", text="Low Poly Preset")
        settings_box.prop(settings, "hue_shift_intensity", slider=True)

        preview_box = layout.box()
        preview_box.label(text="Generated Palette")

        preview_row = preview_box.row(align=True)
        shadow_col = preview_row.column(align=True)
        base_col = preview_row.column(align=True)
        highlight_col = preview_row.column(align=True)

        # Эти поля являются read-only preview: цвет берется из get-callback'ов.
        shadow_col.enabled = False
        base_col.enabled = False
        highlight_col.enabled = False
        shadow_col.prop(settings, "preview_shadow", text="Shadow")
        base_col.prop(settings, "preview_base", text="Base")
        highlight_col.prop(settings, "preview_highlight", text="Highlight")

        preview_box.label(text=f"Roughness: {palette['roughness']:.2f}")

        actions_box = layout.box()
        actions_box.label(text="Apply", icon="MATERIAL_DATA")
        actions_box.operator(
            LOWPOLY_OT_apply_palette_to_faces.bl_idname,
            text="Apply Palette to Selected Faces",
            icon="MATERIAL_DATA",
        )
        actions_box.operator(
            LOWPOLY_OT_apply_to_vertex_colors.bl_idname,
            text="Apply to Vertex Colors",
            icon="BRUSH_DATA",
        )

        hint_box = layout.box()
        hint_box.label(text="Edit Mode: select mesh faces first.", icon="INFO")


# -----------------------------------------------------------------------------
# Register / unregister
# -----------------------------------------------------------------------------

CLASSES = (
    LOWPOLY_PaletteSettings,
    LOWPOLY_OT_apply_palette_to_faces,
    LOWPOLY_OT_apply_to_vertex_colors,
    LOWPOLY_PT_palette_master,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)

    bpy.types.Scene.lowpoly_palette_master = PointerProperty(type=LOWPOLY_PaletteSettings)


def unregister():
    if hasattr(bpy.types.Scene, "lowpoly_palette_master"):
        del bpy.types.Scene.lowpoly_palette_master

    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
