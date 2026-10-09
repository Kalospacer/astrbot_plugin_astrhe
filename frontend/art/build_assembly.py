# ruff: noqa  # 原作者的 Blender 脚本写法（经 exec 共享变量），保持与上游一致便于对照
# AstrHe 拆解查看用的分部件模型（改编自 RhineLabUI 的同名脚本，MIT）。
# 复用 build_archive.py 的建模部分；输出到 frontend/models/，.blend 只写进 art/.cache/。
# 用法：blender -b --factory-startup --python frontend/art/build_assembly.py
import bpy
from pathlib import Path
BUILD_ROOT = Path(__file__).resolve().parents[1]
ROOT = BUILD_ROOT
source = (ROOT/'art/build_archive.py').read_text(encoding='utf-8')
prefix = source.split('# Convert text, bake modifiers')[0]
prefix = prefix.replace("scene = work_scene('AstrHe_Archive_Work')", "scene = work_scene('AstrHe_Assembly_Work')")
prefix = prefix.replace("if old != scene and old.name.startswith('AstrHe_Archive_Asset'):", "if False:")
prefix = prefix.replace("scene.name='AstrHe_Archive_Asset'", "scene.name='AstrHe_Assembly_Asset'")
exec(compile(prefix, str(ROOT/'art/build_archive.py'), 'exec'))
ROOT = BUILD_ROOT
def part_for(name):
    if name.startswith(('Rear translucent carrier', 'Polished perimeter rail', 'Ivory spine cap', 'Carrier mating seam')):
        return 'carrier'
    if name.startswith('Information substrate'): return 'substrate'
    if name.startswith(('Embedded optical cavity', 'Embedded amber annulus', 'Folded optical tab')): return 'optical-core'
    if name.startswith(('Subsurface refractive shoulder', 'Inner optical bevel', 'Concentric optical machining', 'Optical ribbon')):
        return 'optical-lenses'
    if name.startswith(('Countersunk washer', 'Machined screw', 'Screw slot')): return 'fasteners'
    return 'cover'
for obj in list(scene.objects):
    obj['assemblyPart'] = part_for(obj.name)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    if obj.type in ['FONT','CURVE']: bpy.ops.object.convert(target='MESH')
    for mod in list(obj.modifiers):
        bpy.ops.object.modifier_apply(modifier=mod.name)
    if obj.data.materials[0].name.split('.')[0] == 'Carbon_Ink':
        bpy.data.objects.remove(obj, do_unlink=True)
pairs = {}
for obj in scene.objects:
    key = (obj['assemblyPart'], obj.data.materials[0].name)
    pairs.setdefault(key, []).append(obj)
for (part, surface), objects in pairs.items():
    bpy.ops.object.select_all(action='DESELECT')
    for obj in objects: obj.select_set(True)
    bpy.context.view_layer.objects.active = objects[0]
    bpy.ops.object.join()
    obj = bpy.context.object
    obj.name = part+'__'+surface.split('.')[0]
    obj['assemblyPart'] = part
    scene.cursor.location = (0,0,0)
    bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    if surface.startswith(('Optical_Glass_', 'Optical_Bridge_Glass', 'Amber_Optical_Inlay')):
        obj.scale.y *= 2.0
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    else:
        for vertex in obj.data.vertices:vertex.co.y *= 2.0
bpy.ops.object.select_all(action='SELECT')
export_path=ROOT/'art/.cache/archive-assembly.glb'
export_path.parent.mkdir(parents=True,exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(export_path), export_format='GLB', use_selection=True, use_active_scene=True, export_apply=True, export_extras=True)
os.replace(str(export_path),str(ROOT/'models/archive-assembly.glb'))
bpy.data.libraries.write(str(ROOT/'art/.cache/astrhe-assembly.blend'), {scene}, fake_user=True)
print('Assembly exported:', len(scene.objects), 'meshes, parts:', sorted({o['assemblyPart'] for o in scene.objects}))
