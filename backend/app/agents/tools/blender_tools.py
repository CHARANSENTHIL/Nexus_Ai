"""
Blender 3D Tools for Nexus AI Agent Tool Registry.
Provides high-level tools for creating, modifying, and rendering 3D scenes in Blender.
"""
import asyncio
import logging
import os
from typing import Any, Dict, Optional
from langchain_core.tools import tool
from app.agents.blender_agent import blender_agent

logger = logging.getLogger(__name__)


@tool
def create_blender_scene(
    prompt: str,
    filename: str = "scene.blend",
    render_image: bool = True,
    is_animation: bool = False,
    frames: int = 120,
) -> str:
    """
    Creates a new 3D scene in Blender 5.x from natural language description.
    Generates procedural models, PBR materials, cinematic lighting, cameras, renders the scene,
    and saves the .blend project file.
    
    Args:
        prompt: Detailed description of the 3D scene (e.g. 'Low-poly bedroom with bed, desk, chair, warm lighting').
        filename: Target .blend filename (e.g. 'bedroom.blend').
        render_image: Whether to render a high-resolution still image (default True).
        is_animation: Whether to animate and render keyframes (default False).
        frames: Number of animation frames if animated (default 120).
    """
    try:
        try:
            loop = asyncio.get_running_loop()
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                res = pool.submit(
                    asyncio.run,
                    blender_agent.create_scene(
                        prompt=prompt,
                        blend_name=filename,
                        render=render_image,
                        is_animation=is_animation,
                        frames=frames,
                    )
                ).result()
        except RuntimeError:
            res = asyncio.run(
                blender_agent.create_scene(
                    prompt=prompt,
                    blend_name=filename,
                    render=render_image,
                    is_animation=is_animation,
                    frames=frames,
                )
            )

        if not res.get("success"):
            return f"❌ Blender scene creation failed: {res.get('error', 'Unknown error')}"

        blend_path = res.get("blend_file")
        render_path = res.get("render_file")
        review = res.get("vision_review", "")

        out = f"✅ 3D Blender Scene Created Successfully!\n📁 Project File: {blend_path}\n"
        if render_path:
            out += f"📸 Rendered Image: {render_path}\n"
        if review:
            out += f"\n🎨 Vision Art Director Assessment:\n{review}\n"

        return out
    except Exception as e:
        logger.error(f"[blender_tools] create_blender_scene error: {e}", exc_info=True)
        return f"❌ Blender error: {str(e)}"
