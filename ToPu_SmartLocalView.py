bl_info = {
    "name": "ToPu_SmartLocalView",
    "author": "http4211",
    "version": (1, 1, 1),
    "blender": (4, 0, 0),
    "category": "3D View",
    'tracker_url': 'https://github.com/http4211/ToPu_SmartLocalView/tree/main',
    "description": "Hierarchical Local View navigation with selection memory",
}

import bpy
import blf
import gpu
import rna_keymap_ui
from bpy.app.handlers import persistent
from gpu_extras.batch import batch_for_shader

runtime_stack = []
selection_stack = []
display_text = ""
show_overlay = False

addon_keymaps = []
_draw_handler = None


class SmartLocalViewPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    def draw(self, context):
        layout = self.layout
        layout.label(text="Smart Local View キー設定：", icon="PREFERENCES")


        wm = bpy.context.window_manager
        kc = wm.keyconfigs.user

        for km, kmi in addon_keymaps:
            box = layout.box()
            box.label(text=f"Keymap: {km.name}", icon='DOT')
            layout.context_pointer_set("keymap", km)
            rna_keymap_ui.draw_kmi([], kc, km, kmi, box, 0)


class NameItem(bpy.types.PropertyGroup):
    name: bpy.props.StringProperty()


class LocalViewStackLevel(bpy.types.PropertyGroup):
    names: bpy.props.CollectionProperty(type=NameItem)

def get_objects_in_local_view(context):
    # 現在の VIEW_3D の local_view_id を取得
    space = context.space_data
    if not hasattr(space, "local_view") or space.local_view == 0:
        return []

    local_view_id = space.local_view

    # オブジェクトごとに比較
    return [
        obj.name for obj in context.visible_objects
        if getattr(obj, "local_view", 0) == local_view_id
    ]




def draw_callback_px(self, context):
    global display_text, show_overlay
    if not show_overlay:
        return

    region = context.region
    if not region:
        return

    font_id = 0
    font_size = 14  # 小さめのサイズ
    blf.size(font_id, font_size)

    # テキストの描画位置
    text_width, text_height = blf.dimensions(font_id, display_text)
    x = int(region.width / 2 - text_width / 2)
    y = int(region.height - 60)

    # テキスト色を白に設定（RGBA）
    blf.color(font_id, 1.0, 1.0, 1.0, 1.0)

    # テキスト描画
    blf.position(font_id, x, y, 0)
    blf.draw(font_id, display_text)



def toggle_local_view():
    try:
        bpy.ops.view3d.localview('INVOKE_DEFAULT', frame_selected=False)
    except RuntimeError as e:
        print(f"[SmartLocalView] Error: {e}")



class VIEW3D_OT_smart_local_view(bpy.types.Operator):
    bl_idname = "view3d.smart_local_view"
    bl_label = "Smart Local View"
    bl_description = "Enter and exit local view hierarchically, remembering selection state"

    def execute(self, context):
        global runtime_stack, selection_stack, display_text, show_overlay

        #print("\n[SmartLocalView] --- Execute Start ---")

        selected_objs = set(context.selected_objects)
        selected_names = set(obj.name for obj in selected_objs)
        in_local = context.space_data.local_view

        #print(f"[SmartLocalView] LocalView: {in_local}")
        #print(f"[SmartLocalView] Selected: {selected_names}")
        #print(f"[SmartLocalView] RuntimeStack Depth: {len(runtime_stack)}")

        def apply_selection(names):
            #print(f"[SmartLocalView] Applying selection: {names}")
            bpy.ops.object.select_all(action='DESELECT')
            objs = [bpy.data.objects.get(name) for name in names if name in bpy.data.objects]
            for obj in objs:
                obj.select_set(True)
            if objs:
                context.view_layer.objects.active = objs[0]

        def get_all_visible_names(context):
            return {obj.name for obj in context.visible_objects}

        def record_diff_and_restore(context):
            prev_selection = set(obj.name for obj in context.selected_objects)
            bpy.ops.object.select_all(action='SELECT')
            all_visible = get_all_visible_names(context)
            known = set().union(*runtime_stack)
            new_names = all_visible - known
            #print(f"[SmartLocalView] All Visible: {all_visible}")
            #print(f"[SmartLocalView] Known in Stack: {known}")
            #print(f"[SmartLocalView] New Names Detected: {new_names}")
            for level in runtime_stack:
                level.update(new_names)
            for level in selection_stack:
                level.update(new_names)
            bpy.ops.object.select_all(action='DESELECT')
            for name in prev_selection:
                if name in bpy.data.objects:
                    bpy.data.objects[name].select_set(True)
            if prev_selection:
                context.view_layer.objects.active = bpy.data.objects.get(next(iter(prev_selection), None))

        if not in_local:
            if selected_objs:
                #print("[SmartLocalView] ENTER Local View (First time)")
                runtime_stack.clear()
                selection_stack.clear()
                runtime_stack.append(selected_names.copy())
                selection_stack.append(selected_names.copy())
                self.save_stack_to_scene(context)
                toggle_local_view()
                display_text = f"Local View:   Level {len(runtime_stack)}"
                show_overlay = True
        else:
            current_selection = selected_names
            current_level = runtime_stack[-1]

            if current_selection == current_level or not selected_objs:
                #print("[SmartLocalView] Attempt to move UP a level")
                if len(runtime_stack) > 1:
                    record_diff_and_restore(context)
                    had_selection = bool(selected_objs)
                    pre_pop_selection = current_selection.copy()

                    runtime_stack.pop()
                    selection_stack.pop()
                    self.save_stack_to_scene(context)
                    #print(f"[SmartLocalView] Stack popped. New depth: {len(runtime_stack)}")

                    toggle_local_view()

                    target_level = runtime_stack[-1]
                    bpy.ops.object.select_all(action='DESELECT')
                    for name in target_level:
                        if name in bpy.data.objects:
                            bpy.data.objects[name].select_set(True)
                    context.view_layer.objects.active = bpy.data.objects.get(next(iter(target_level), None))

                    toggle_local_view()

                    if had_selection and pre_pop_selection:
                        apply_selection(pre_pop_selection)
                    else:
                        bpy.ops.object.select_all(action='DESELECT')

                    display_text = f"Local View: Level {len(runtime_stack)}"
                    show_overlay = True
                else:
                    #print("[SmartLocalView] Exiting Local View")
                    runtime_stack.clear()
                    selection_stack.clear()
                    self.save_stack_to_scene(context)
                    toggle_local_view()
                    display_text = ""
                    show_overlay = False
            elif selected_objs:
                #print("[SmartLocalView] Going DOWN a level")
                record_diff_and_restore(context)

                runtime_stack.append(selected_names.copy())
                selection_stack.append(selected_names.copy())
                self.save_stack_to_scene(context)
                #print(f"[SmartLocalView] Stack pushed. New depth: {len(runtime_stack)}")

                toggle_local_view()
                toggle_local_view()
                display_text = f"Local View: Level {len(runtime_stack)}"
                show_overlay = True

        #print("[SmartLocalView] --- Execute End ---\n")
        return {'FINISHED'}





    def save_stack_to_scene(self, context):
        scene = context.scene
        scene.smart_local_view_stack.clear()
        for level in selection_stack:
            lv = scene.smart_local_view_stack.add()
            for name in level:
                item = lv.names.add()
                item.name = name

    @classmethod
    def poll(cls, context):
        return context.area.type == 'VIEW_3D'


@persistent
def load_stack_post(dummy):
    global runtime_stack, selection_stack
    runtime_stack.clear()
    selection_stack.clear()
    scene = bpy.context.scene
    if not hasattr(scene, "smart_local_view_stack"):
        return
    for level in scene.smart_local_view_stack:
        names = {item.name for item in level.names if item.name in bpy.data.objects}
        runtime_stack.append(names)
        selection_stack.append(names)


classes = (
    SmartLocalViewPreferences,
    NameItem,
    LocalViewStackLevel,
    VIEW3D_OT_smart_local_view,
)


def register_keymap():
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    if not kc:
        return

    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    kmi = km.keymap_items.new(SmartLocalViewOperator.bl_idname, type='NUMPAD_SLASH', value='PRESS')
    addon_keymaps.append((km, kmi))


def unregister_keymap():
    for km, kmi in addon_keymaps:
        km.keymap_items.remove(kmi)
    addon_keymaps.clear()


def register():
    global _draw_handler
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.smart_local_view_stack = bpy.props.CollectionProperty(type=LocalViewStackLevel)

    register_keymap()

    if load_stack_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(load_stack_post)

    _draw_handler = bpy.types.SpaceView3D.draw_handler_add(draw_callback_px, (None, bpy.context), 'WINDOW', 'POST_PIXEL')


def unregister():
    global _draw_handler
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    if hasattr(bpy.types.Scene, "smart_local_view_stack"):
        del bpy.types.Scene.smart_local_view_stack

    unregister_keymap()

    if load_stack_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(load_stack_post)

    if _draw_handler:
        bpy.types.SpaceView3D.draw_handler_remove(_draw_handler, 'WINDOW')
        _draw_handler = None


if __name__ == "__main__":
    register()
