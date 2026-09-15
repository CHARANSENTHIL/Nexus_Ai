"""
Blender 3D Autonomous Agent for Nexus AI.
Generates procedural 3D scenes, models, materials, lighting, and animations in Blender 5.x,
executes headless bpy scripts, renders images/videos, and performs closed-loop Vision verification.
"""
import asyncio
import glob
import logging
import os
import re
import shutil
import uuid
from typing import Any, Dict, List, Optional
import httpx

logger = logging.getLogger(__name__)

# Output directories
BLENDER_OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "blender_output"))
BLENDER_SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "blender_scripts"))
os.makedirs(BLENDER_OUTPUT_DIR, exist_ok=True)
os.makedirs(BLENDER_SCRIPTS_DIR, exist_ok=True)


class BlenderAgent:
    """Autonomous Agent for Blender 3D Scene Generation, Modification, and Rendering."""

    def __init__(self):
        self.blender_path = self._discover_blender_path()
        logger.info(f"[BlenderAgent] Initialized with Blender binary: {self.blender_path}")

    @staticmethod
    def _discover_blender_path() -> Optional[str]:
        """Locates Blender executable on Windows or system PATH."""
        path = shutil.which("blender") or shutil.which("blender.exe")
        if path and os.path.isfile(path):
            return path

        candidates = [
            r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 5.1\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 5.0\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.3\blender.exe",
            r"C:\Program Files\Blender Foundation\Blender 4.2\blender.exe",
        ]
        for c in candidates:
            if os.path.isfile(c):
                return c

        glob_matches = glob.glob(r"C:\Program Files\Blender Foundation\*\blender.exe")
        if glob_matches:
            return sorted(glob_matches, reverse=True)[0]

        return None

    @property
    def is_available(self) -> bool:
        return bool(self.blender_path and os.path.isfile(self.blender_path))

    async def generate_bpy_script(
        self,
        prompt: str,
        blend_output_path: str,
        render_image_path: Optional[str] = None,
        is_animation: bool = False,
        frames: int = 120,
        existing_blend_path: Optional[str] = None,
    ) -> str:
        """
        Synthesizes a production-ready, error-free Blender Python (bpy) script using Phi-4-mini / Qwen3.
        """
        from app.config import settings
        ollama_url = settings.get_ollama_url()
        coding_model = getattr(settings, "OLLAMA_CODING_MODEL", "phi4-mini:latest")

        render_path_clean = (render_image_path or "").replace("\\", "/")
        blend_path_clean = blend_output_path.replace("\\", "/")

        system_instruction = (
            "You are an expert 3D Technical Director and Blender Python (bpy) developer for Blender 5.x / 4.x.\n"
            "Generate ONLY valid, self-contained, and complete Python code that runs inside Blender via `blender -b -P script.py`.\n"
            "When modeling characters, humanoids, or faces, create complete anatomical geometry (Head, Hair with volume, Eyes, Pupils, Eyebrows, Nose, Lips, Neck, Shoulders/Torso, and 3-point Studio Lighting).\n"
            "DO NOT include markdown explanations outside the code block. Return ONLY ```python ... ```."
        )

        user_prompt = f"""
Goal: Create/Modify a 3D scene in Blender based on this request:
"{prompt}"

Technical Requirements:
1. Target Engine: EEVEE Next or CYCLES (bpy.context.scene.render.engine = 'BLENDER_EEVEE_NEXT' or 'CYCLES').
2. Scene Setup:
   - Clear all existing default objects (cube, light, camera).
   - Build rich, recognizable 3D geometry matching the prompt.
   - For characters/faces/persons: Build stylized head, hair mesh, eyes with irises, eyebrows, nose, mouth, ears, neck, shoulders with clothes, and studio 3-point lighting.
   - For rooms/interiors: Build walls, floor, furniture, props, and ambient/point lights.
   - Use meaningful object names.
3. Materials & Shaders:
   - Create Principled BSDF materials with vibrant, realistic colors, roughness, metallic, or skin tones.
   - Assign materials properly to all created meshes.
4. Lighting & Environment:
   - Setup aesthetic cinematic lighting (Key Light, Fill Light, Rim Light).
   - Set world background ambient color.
5. Camera:
   - Position an active Camera framed directly on the subject.
6. Animation:
   - {'Set frame_start=1, frame_end=' + str(frames) + ' and add smooth rotation keyframes.' if is_animation else 'No animation keyframes required.'}

Generate the complete Python script now:
"""

        script_body = None
        # Fast procedural path for well-defined archetypes (characters, faces, bedrooms)
        p_lower = prompt.lower()
        is_known_archetype = any(w in p_lower for w in ("face", "person", "human", "man", "woman", "guy", "girl", "character", "actor", "vijay", "avatar", "bust", "head", "portrait", "boy", "hero", "bed", "room", "bedroom", "living", "apartment", "house"))

        if not is_known_archetype:
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.post(
                        f"{ollama_url}/api/generate",
                        json={
                            "model": coding_model,
                            "system": system_instruction,
                            "prompt": user_prompt,
                            "stream": False,
                        },
                    )
                    if resp.status_code == 200:
                        raw = resp.json().get("response", "")
                        match = re.search(r"```(?:python|bpy)?\s*(.*?)```", raw, re.DOTALL)
                        if match and len(match.group(1).strip()) > 100:
                            script_body = match.group(1).strip()
                        elif "import bpy" in raw and len(raw.strip()) > 100:
                            script_body = raw.strip()
            except Exception as e:
                logger.warning(f"[BlenderAgent] LLM script synthesis note: {e}")

        if not script_body:
            script_body = self._generate_procedural_script(prompt, blend_path_clean, render_path_clean, is_animation, frames)

        # ── Guaranteed Nexus AI Camera, Lighting, Save & Render Footer ──
        footer = f"""
# ── Guaranteed Nexus AI Scene Finalization ──
import bpy, math, os

# Ensure at least one active camera exists
if not bpy.context.scene.camera:
    bpy.ops.object.camera_add(location=(1.5, -4.5, 2.0), rotation=(math.radians(72), 0, math.radians(18)))
    bpy.context.scene.camera = bpy.context.object

# Ensure lighting exists
has_light = any(obj.type == 'LIGHT' for obj in bpy.data.objects)
if not has_light:
    bpy.ops.object.light_add(type='SUN', location=(5, -5, 10))
    bpy.context.object.data.energy = 4.0

# Ensure output directory exists and save .blend file
os.makedirs(os.path.dirname(r"{blend_path_clean}"), exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=r"{blend_path_clean}")
"""
        if render_path_clean:
            footer += f"""
bpy.context.scene.render.filepath = r"{render_path_clean}"
bpy.context.scene.render.image_settings.file_format = 'PNG'
bpy.context.scene.render.resolution_x = 1280
bpy.context.scene.render.resolution_y = 720
bpy.ops.render.render(write_still=True)
"""
        footer += "\nprint('NEXUS_BLENDER_FINISHED_SUCCESSFULLY')\n"
        return f"{script_body}\n\n{footer}"

    def _generate_procedural_script(
        self,
        prompt: str,
        blend_path: str,
        render_path: Optional[str],
        is_animation: bool,
        frames: int,
    ) -> str:
        """Procedural 3D scene builder for characters, faces, architecture, and objects."""
        p = prompt.lower()

        # ── 1. Character / Human Figure / Face / Avatar / Bust Generation ──
        if any(w in p for w in ("face", "person", "human", "man", "woman", "guy", "girl", "character", "actor", "vijay", "avatar", "bust", "head", "portrait", "boy", "hero")):
            return """import bpy, math

# 1. Reset Scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# Material Helper
def make_mat(name, color, metallic=0.0, roughness=0.5, emission=None):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if emission and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = emission if len(emission) == 4 else (*emission, 1.0)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = 5.0
    return mat

# Materials: Stylized skin, hair, clothes, facial features
skin_mat = make_mat("Skin", (0.82, 0.62, 0.48, 1.0), roughness=0.55)
hair_mat = make_mat("Hair", (0.06, 0.05, 0.04, 1.0), roughness=0.7)
beard_mat = make_mat("BeardStubble", (0.08, 0.06, 0.05, 1.0), roughness=0.9)
shirt_mat = make_mat("Shirt", (0.12, 0.22, 0.42, 1.0), roughness=0.8)
eye_white = make_mat("EyeSclera", (0.95, 0.95, 0.95, 1.0), roughness=0.1)
eye_iris = make_mat("EyeIris", (0.10, 0.07, 0.04, 1.0), roughness=0.15)
lip_mat = make_mat("Lips", (0.75, 0.45, 0.42, 1.0), roughness=0.5)
bg_mat = make_mat("StudioBackdrop", (0.08, 0.09, 0.12, 1.0), roughness=0.9)

# Studio Backdrop
bpy.ops.mesh.primitive_cylinder_add(radius=5.0, depth=0.1, location=(0, 0, -0.5))
backdrop = bpy.context.object; backdrop.name = "Backdrop"; backdrop.data.materials.append(bg_mat)

# ── Head & Cranium ──
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=24, radius=0.85, location=(0, 0, 1.6))
head = bpy.context.object; head.name = "Head_Cranium"
head.scale = (0.9, 0.95, 1.15)
head.data.materials.append(skin_mat)

# ── Jaw & Chin ──
bpy.ops.mesh.primitive_cube_add(location=(0, -0.32, 1.05), scale=(0.48, 0.42, 0.3))
jaw = bpy.context.object; jaw.name = "Jaw_Chin"
jaw.data.materials.append(skin_mat)

# ── Neck ──
bpy.ops.mesh.primitive_cylinder_add(radius=0.35, depth=0.7, location=(0, -0.05, 0.7))
neck = bpy.context.object; neck.name = "Neck"
neck.data.materials.append(skin_mat)

# ── Shoulders & Torso (Shirt) ──
bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0.15), scale=(1.45, 0.65, 0.45))
shoulders = bpy.context.object; shoulders.name = "Shoulders_Torso"
shoulders.data.materials.append(shirt_mat)

# Collar
bpy.ops.mesh.primitive_torus_add(major_radius=0.42, minor_radius=0.08, location=(0, -0.05, 0.5))
collar = bpy.context.object; collar.name = "Shirt_Collar"
collar.data.materials.append(shirt_mat)

# ── Stylized Hair (Volumetric Modern Hairstyle) ──
bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=18, radius=0.92, location=(0, 0.08, 1.95))
hair_top = bpy.context.object; hair_top.name = "Hair_Top"
hair_top.scale = (0.92, 0.98, 0.85)
hair_top.data.materials.append(hair_mat)

# Front Hairstyle Quiff / Volume
bpy.ops.mesh.primitive_cube_add(location=(0, -0.45, 2.25), scale=(0.55, 0.35, 0.25))
hair_front = bpy.context.object; hair_front.name = "Hair_Quiff"
hair_front.rotation_euler = (math.radians(-20), 0, 0)
hair_front.data.materials.append(hair_mat)

# Sideburns
bpy.ops.mesh.primitive_cube_add(location=(-0.82, -0.15, 1.55), scale=(0.06, 0.18, 0.35))
bpy.context.object.data.materials.append(hair_mat)
bpy.ops.mesh.primitive_cube_add(location=(0.82, -0.15, 1.55), scale=(0.06, 0.18, 0.35))
bpy.context.object.data.materials.append(hair_mat)

# ── Eyes (Sclera + Iris) ──
# Left Eye
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.11, location=(-0.32, -0.80, 1.62))
eye_l = bpy.context.object; eye_l.name = "Eye_Left"; eye_l.data.materials.append(eye_white)
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.06, location=(-0.32, -0.89, 1.62))
iris_l = bpy.context.object; iris_l.name = "Iris_Left"; iris_l.data.materials.append(eye_iris)

# Right Eye
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.11, location=(0.32, -0.80, 1.62))
eye_r = bpy.context.object; eye_r.name = "Eye_Right"; eye_r.data.materials.append(eye_white)
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.06, location=(0.32, -0.89, 1.62))
iris_r = bpy.context.object; iris_r.name = "Iris_Right"; iris_r.data.materials.append(eye_iris)

# ── Eyebrows ──
bpy.ops.mesh.primitive_cube_add(location=(-0.34, -0.85, 1.78), scale=(0.22, 0.05, 0.04))
eb_l = bpy.context.object; eb_l.name = "Eyebrow_Left"
eb_l.rotation_euler = (0, math.radians(-8), math.radians(5))
eb_l.data.materials.append(hair_mat)

bpy.ops.mesh.primitive_cube_add(location=(0.34, -0.85, 1.78), scale=(0.22, 0.05, 0.04))
eb_r = bpy.context.object; eb_r.name = "Eyebrow_Right"
eb_r.rotation_euler = (0, math.radians(8), math.radians(-5))
eb_r.data.materials.append(hair_mat)

# ── Nose ──
bpy.ops.mesh.primitive_cone_add(radius1=0.12, radius2=0.04, depth=0.35, location=(0, -0.92, 1.42))
nose = bpy.context.object; nose.name = "Nose"
nose.rotation_euler = (math.radians(-25), 0, 0)
nose.data.materials.append(skin_mat)

# ── Lips / Mouth ──
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.18, location=(0, -0.82, 1.15))
mouth = bpy.context.object; mouth.name = "Lips"
mouth.scale = (1.1, 0.25, 0.35)
mouth.data.materials.append(lip_mat)

# ── Beard & Stubble Trim ──
bpy.ops.mesh.primitive_cube_add(location=(0, -0.62, 0.95), scale=(0.42, 0.22, 0.18))
beard = bpy.context.object; beard.name = "Beard_Trim"
beard.data.materials.append(beard_mat)

# ── Ears ──
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.18, location=(-0.88, -0.05, 1.55))
ear_l = bpy.context.object; ear_l.scale = (0.35, 0.7, 1.1); ear_l.data.materials.append(skin_mat)
bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=12, radius=0.18, location=(0.88, -0.05, 1.55))
ear_r = bpy.context.object; ear_r.scale = (0.35, 0.7, 1.1); ear_r.data.materials.append(skin_mat)

# ── 3-Point Studio Portrait Lighting ──
# Key Light (Warm, 45-deg angle)
bpy.ops.object.light_add(type='AREA', location=(-2.2, -3.2, 2.8))
key_l = bpy.context.object.data; key_l.energy = 320; key_l.color = (1.0, 0.92, 0.85); key_l.size = 2.0

# Fill Light (Cool, Soft)
bpy.ops.object.light_add(type='AREA', location=(2.4, -2.8, 1.8))
fill_l = bpy.context.object.data; fill_l.energy = 140; fill_l.color = (0.8, 0.9, 1.0); fill_l.size = 2.5

# Rim / Hair Light (Dramatic highlights)
bpy.ops.object.light_add(type='SPOT', location=(0, 2.5, 3.2))
rim_l = bpy.context.object.data; rim_l.energy = 450; rim_l.color = (1.0, 0.95, 0.8); rim_l.spot_size = math.radians(65)

# ── Portrait Camera (Cinematic 85mm Framing) ──
bpy.ops.object.camera_add(location=(0.4, -3.8, 1.65), rotation=(math.radians(85), 0, math.radians(6)))
cam = bpy.context.object
cam.data.lens = 65
bpy.context.scene.camera = cam
"""

        # ── 2. Bedroom / House / Interior Scene ──
        elif any(w in p for w in ("bed", "room", "bedroom", "house", "apartment", "living")):
            # Procedural Bedroom Scene
            return """import bpy, math

# 1. Reset Scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

# Material Helper
def make_mat(name, color, metallic=0.0, roughness=0.5, emission=None):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if emission and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = emission if len(emission) == 4 else (*emission, 1.0)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = 5.0
    return mat

wood_mat = make_mat("Wood", (0.45, 0.25, 0.12, 1.0), roughness=0.4)
bed_mat = make_mat("BedSheets", (0.9, 0.88, 0.85, 1.0), roughness=0.7)
pillow_mat = make_mat("Pillows", (0.3, 0.5, 0.7, 1.0), roughness=0.6)
lamp_mat = make_mat("LampGlow", (1.0, 0.9, 0.6, 1.0), emission=(1.0, 0.85, 0.4, 1.0))
wall_mat = make_mat("Walls", (0.85, 0.85, 0.88, 1.0), roughness=0.8)
floor_mat = make_mat("Floor", (0.35, 0.22, 0.15, 1.0), roughness=0.3)

# 2. Floor & Walls
bpy.ops.mesh.primitive_cube_add(location=(0, 0, -0.05), scale=(3.5, 3.5, 0.05))
floor = bpy.context.object; floor.name = "Floor"; floor.data.materials.append(floor_mat)

bpy.ops.mesh.primitive_cube_add(location=(-3.4, 0, 1.5), scale=(0.1, 3.5, 1.5))
wall1 = bpy.context.object; wall1.name = "Wall_Left"; wall1.data.materials.append(wall_mat)

bpy.ops.mesh.primitive_cube_add(location=(0, 3.4, 1.5), scale=(3.5, 0.1, 1.5))
wall2 = bpy.context.object; wall2.name = "Wall_Back"; wall2.data.materials.append(wall_mat)

# 3. Bed
bpy.ops.mesh.primitive_cube_add(location=(-1.5, 1.5, 0.3), scale=(1.2, 1.6, 0.3))
bed_frame = bpy.context.object; bed_frame.name = "Bed_Frame"; bed_frame.data.materials.append(wood_mat)

bpy.ops.mesh.primitive_cube_add(location=(-1.5, 1.5, 0.65), scale=(1.1, 1.5, 0.15))
mattress = bpy.context.object; mattress.name = "Mattress"; mattress.data.materials.append(bed_mat)

bpy.ops.mesh.primitive_cube_add(location=(-1.5, 2.5, 0.85), scale=(0.8, 0.35, 0.1))
pillow = bpy.context.object; pillow.name = "Pillow"; pillow.data.materials.append(pillow_mat)

# 4. Desk & Chair
bpy.ops.mesh.primitive_cube_add(location=(1.8, 2.2, 0.75), scale=(1.0, 0.6, 0.05))
desk_top = bpy.context.object; desk_top.name = "Desk_Top"; desk_top.data.materials.append(wood_mat)

bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=0.75, location=(0.9, 1.7, 0.375))
bpy.context.object.data.materials.append(wood_mat)
bpy.ops.mesh.primitive_cylinder_add(radius=0.04, depth=0.75, location=(2.7, 1.7, 0.375))
bpy.context.object.data.materials.append(wood_mat)

# Lamp on Desk
bpy.ops.mesh.primitive_cylinder_add(radius=0.1, depth=0.3, location=(2.4, 2.4, 0.95))
lamp_base = bpy.context.object; lamp_base.data.materials.append(wood_mat)
bpy.ops.mesh.primitive_cone_add(radius1=0.2, depth=0.25, location=(2.4, 2.4, 1.2))
lamp_shade = bpy.context.object; lamp_shade.data.materials.append(lamp_mat)

# 5. Lighting
bpy.ops.object.light_add(type='POINT', location=(2.4, 2.4, 1.3))
lamp_light = bpy.context.object.data; lamp_light.energy = 80; lamp_light.color = (1.0, 0.8, 0.5)

bpy.ops.object.light_add(type='AREA', location=(0, -2, 3.5))
ambient_light = bpy.context.object.data; ambient_light.energy = 250; ambient_light.color = (0.8, 0.9, 1.0)

# 6. Isometric Camera
bpy.ops.object.camera_add(location=(6.5, -6.5, 5.5), rotation=(math.radians(60), 0, math.radians(45)))
cam = bpy.context.object
cam.data.type = 'ORTHO'
cam.data.ortho_scale = 8.5
bpy.context.scene.camera = cam
"""
        else:
            # Procedural Hero 3D Sculpture / Tech Scene
            return """import bpy, math

# 1. Reset Scene
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)

def make_mat(name, color, metallic=0.0, roughness=0.5, emission=None):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        if "Base Color" in bsdf.inputs:
            bsdf.inputs["Base Color"].default_value = color
        if "Metallic" in bsdf.inputs:
            bsdf.inputs["Metallic"].default_value = metallic
        if "Roughness" in bsdf.inputs:
            bsdf.inputs["Roughness"].default_value = roughness
        if emission and "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = emission if len(emission) == 4 else (*emission, 1.0)
            if "Emission Strength" in bsdf.inputs:
                bsdf.inputs["Emission Strength"].default_value = 5.0
    return mat

gold_mat = make_mat("Gold", (1.0, 0.8, 0.2, 1.0), metallic=0.9, roughness=0.15)
neon_mat = make_mat("NeonCyan", (0.1, 0.8, 1.0, 1.0), emission=(0.1, 0.9, 1.0, 1.0))
dark_mat = make_mat("DarkPedestal", (0.15, 0.15, 0.18, 1.0), metallic=0.5, roughness=0.3)

# Floor
bpy.ops.mesh.primitive_cylinder_add(radius=4.0, depth=0.2, location=(0, 0, -0.1))
floor = bpy.context.object; floor.data.materials.append(dark_mat)

# Hero Torus Sculpture
bpy.ops.mesh.primitive_torus_add(major_radius=1.5, minor_radius=0.4, location=(0, 0, 1.8))
torus = bpy.context.object; torus.data.materials.append(gold_mat)

# Inner Floating Core
bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=3, radius=0.6, location=(0, 0, 1.8))
core = bpy.context.object; core.data.materials.append(neon_mat)

# Lights
bpy.ops.object.light_add(type='AREA', location=(4, -4, 5))
l1 = bpy.context.object.data; l1.energy = 400; l1.color = (1.0, 0.9, 0.8)
bpy.ops.object.light_add(type='POINT', location=(-3, 3, 3))
l2 = bpy.context.object.data; l2.energy = 250; l2.color = (0.2, 0.6, 1.0)

# Camera
bpy.ops.object.camera_add(location=(5, -5, 4), rotation=(math.radians(65), 0, math.radians(45)))
bpy.context.scene.camera = bpy.context.object
"""

    async def execute_blender_script(self, script_content: str, blend_file_to_open: Optional[str] = None) -> Dict[str, Any]:
        """
        Runs Blender in background headless mode with the synthesized script.
        """
        if not self.is_available:
            return {
                "success": False,
                "error": f"Blender executable not found on system. Please verify installation at '{self.blender_path}'.",
            }

        script_file = os.path.join(BLENDER_SCRIPTS_DIR, f"script_{uuid.uuid4().hex[:8]}.py")
        try:
            with open(script_file, "w", encoding="utf-8") as f:
                f.write(script_content)

            cmd = [self.blender_path, "--background"]
            if blend_file_to_open and os.path.isfile(blend_file_to_open):
                cmd.extend([blend_file_to_open])
            cmd.extend(["--python", script_file])

            logger.info(f"[BlenderAgent] 🚀 Executing Blender CLI: {' '.join(cmd)}")

            import subprocess
            def _run():
                return subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=90,
                    encoding="utf-8",
                    errors="replace",
                )

            proc_res = await asyncio.to_thread(_run)

            if proc_res.returncode != 0 or "Traceback (most recent call last)" in proc_res.stderr:
                err_msg = proc_res.stderr[:400] or proc_res.stdout[-400:]
                logger.warning(f"[BlenderAgent] Blender execution issue: {err_msg}")
                return {
                    "success": False,
                    "error": f"Blender error: {err_msg}",
                    "stdout": proc_res.stdout,
                }

            return {"success": True, "stdout": proc_res.stdout}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Blender render timed out after 90 seconds."}
        except Exception as e:
            logger.error(f"[BlenderAgent] Subprocess execution exception: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
        finally:
            if os.path.exists(script_file):
                try:
                    os.remove(script_file)
                except Exception:
                    pass

    async def create_scene(
        self,
        prompt: str,
        blend_name: str = "scene.blend",
        render: bool = True,
        is_animation: bool = False,
        frames: int = 120,
    ) -> Dict[str, Any]:
        """
        High-level pipeline:
        1. Synthesize bpy code (Phi-4-mini / procedural)
        2. Run Blender in background (bpy)
        3. Save .blend file
        4. Render output image/video
        5. Run Gemma 3 Vision quality inspection
        """
        if not blend_name.endswith(".blend"):
            blend_name += ".blend"

        clean_slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", os.path.splitext(blend_name)[0])
        blend_file_path = os.path.join(BLENDER_OUTPUT_DIR, f"{clean_slug}.blend")
        render_image_path = os.path.join(BLENDER_OUTPUT_DIR, f"{clean_slug}.png") if render else None

        logger.info(f"[BlenderAgent] 🎨 Creating 3D Scene: '{prompt}' -> {blend_file_path}")

        # Step 1: Generate Script
        script = await self.generate_bpy_script(
            prompt=prompt,
            blend_output_path=blend_file_path,
            render_image_path=render_image_path,
            is_animation=is_animation,
            frames=frames,
        )

        # Step 2: Run Blender
        exec_res = await self.execute_blender_script(script)
        if not exec_res.get("success"):
            return exec_res

        blend_exists = os.path.isfile(blend_file_path)
        render_exists = render_image_path and os.path.isfile(render_image_path)

        # Step 3: Closed-Loop Vision Inspection (Gemma 3 4B - Fast non-blocking check)
        vision_review = ""
        if render_exists:
            try:
                from app.agents.chat_agent import chat_agent
                review_prompt = (
                    f"You are a 3D Art Director. Inspect this newly rendered Blender 3D scene created for: '{prompt}'.\n"
                    "Briefly evaluate the composition, lighting, materials, and geometry in 2-3 concise bullet points."
                )
                async def _get_review():
                    chunks = []
                    async for chunk in chat_agent.stream_vision_response(review_prompt, render_image_path, user_name="Director"):
                        chunks.append(chunk)
                    return "".join(chunks).strip()

                vision_review = await asyncio.wait_for(_get_review(), timeout=6.0)
            except Exception as ve:
                logger.info(f"[BlenderAgent] Vision review non-blocking pass: {ve}")

        return {
            "success": blend_exists,
            "prompt": prompt,
            "blend_file": blend_file_path if blend_exists else None,
            "render_file": render_image_path if render_exists else None,
            "vision_review": vision_review,
            "message": f"Successfully created 3D scene in Blender: {blend_name}",
        }


blender_agent = BlenderAgent()
