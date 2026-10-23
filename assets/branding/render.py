#!/usr/bin/env python3
"""Render original SVG artwork with installed librsvg/Cairo; no network or pip.

Run from any directory. Requires librsvg-2, Cairo and DejaVu Sans.
PNG files are Supervisor repository assets, never copied into the runtime.
"""
import ctypes as C
import ctypes.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]

def library(name):
    path = ctypes.util.find_library(name)
    if not path:
        raise SystemExit(f"Required rendering library is missing: {name}")
    return C.CDLL(path)

def bind(lib, name, result, *args):
    function = getattr(lib, name)
    function.restype, function.argtypes = result, list(args)
    return function

def render():
    cairo, rsvg, objects = library('cairo'), library('rsvg-2'), library('gobject-2.0')
    surface_new = bind(cairo, 'cairo_image_surface_create', C.c_void_p, C.c_int, C.c_int, C.c_int)
    context_new = bind(cairo, 'cairo_create', C.c_void_p, C.c_void_p)
    handle_new = bind(rsvg, 'rsvg_handle_new_from_file', C.c_void_p, C.c_char_p, C.c_void_p)
    draw = bind(rsvg, 'rsvg_handle_render_cairo', C.c_int, C.c_void_p, C.c_void_p)
    write = bind(cairo, 'cairo_surface_write_to_png', C.c_int, C.c_void_p, C.c_char_p)
    destroy = bind(cairo, 'cairo_destroy', None, C.c_void_p)
    surface_destroy = bind(cairo, 'cairo_surface_destroy', None, C.c_void_p)
    unref = bind(objects, 'g_object_unref', None, C.c_void_p)
    for name, width, height in [('icon', 128, 128), ('logo', 250, 100)]:
        handle = handle_new(str(HERE / f'{name}.svg').encode(), None)
        if not handle:
            raise SystemExit(f'Invalid SVG: {name}')
        surface = surface_new(0, width, height)  # ARGB32, initially transparent
        context = context_new(surface)
        try:
            if not draw(handle, context):
                raise SystemExit(f'Rendering failed: {name}')
            if write(surface, str(ROOT / 'danfoss_link' / f'{name}.png').encode()):
                raise SystemExit(f'PNG export failed: {name}')
        finally:
            destroy(context)
            surface_destroy(surface)
            unref(handle)

if __name__ == '__main__':
    render()
