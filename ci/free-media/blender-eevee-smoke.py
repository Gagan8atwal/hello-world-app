"""Synthetic open-source runtime smoke test, not private PikoPop engine code."""
import bpy
import hashlib
from pathlib import Path
from mathutils import Vector

bpy.ops.object.select_all(action="SELECT")
bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene
engines={item.identifier for item in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items}
preferred="BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
if preferred not in engines:
    raise RuntimeError("FREE_RUNTIME_EEVEE_NOT_AVAILABLE:" + ",".join(sorted(engines)))
scene.render.engine=preferred
scene.render.resolution_x=96
scene.render.resolution_y=54
scene.render.resolution_percentage=100
scene.render.image_settings.file_format="PNG"
bpy.ops.mesh.primitive_cube_add(size=1.5,location=(0,0,0))
bpy.ops.object.camera_add(location=(2,-5,3))
cam=bpy.context.object
cam.rotation_euler=(Vector((0,0,0))-cam.location).to_track_quat("-Z","Y").to_euler()
scene.camera=cam
bpy.ops.object.light_add(type="AREA",location=(1,-3,4))
bpy.context.object.data.energy=900
output=Path("qa-proof/eevee-smoke.png")
output.parent.mkdir(parents=True,exist_ok=True)
scene.render.filepath=str(output.resolve())
bpy.ops.render.render(write_still=True)
if not output.exists() or output.stat().st_size<200:
    raise RuntimeError("FREE_RUNTIME_EEVEE_PIXEL_RENDER_FAILED")
print(f"FREE_RUNTIME_EEVEE_PIXEL_RENDER_PASS backend={preferred} sha256={hashlib.sha256(output.read_bytes()).hexdigest()} bytes={output.stat().st_size}")
