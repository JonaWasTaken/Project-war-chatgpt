"""Build explicit new Principled materials in a NEW Blender snapshot; never save the source.

Use official bpy Python or Blender --background --disable-autoexec --python
build_pbr.py -- --source existing.blend --spec filled.json --output NEW.blend
--report NEW.json. See references/pbr-builder.md for the bounded schema.
"""
import argparse
import json
from pathlib import Path
import re
import sys

# Blender --python/runpy need not add this script's directory to sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reconstruct_vehicle import check_paths, digest, keys, number, save_snapshot, text


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def unit(value, label):
    result = number(value, label)
    if not 0 <= result <= 1:
        raise ValueError(label + ' must be in [0, 1]')
    return result


def validate_map(value, spec_path, normal=False):
    keys(value, ('path', 'sha256', 'size') + (('convention',) if normal else ()))
    if normal and value['convention'] not in ('OpenGL', 'DirectX'):
        raise ValueError('normal convention must be explicitly OpenGL or DirectX tangent space')
    raw = value['path']
    if not isinstance(raw, str) or not raw.strip() or '\x00' in raw:
        raise ValueError('texture path must be a nonempty file path')
    if not isinstance(value['sha256'], str) or not re.fullmatch('[0-9a-f]{64}', value['sha256']):
        raise ValueError('texture sha256 must be lowercase 64-character hexadecimal')
    size = value['size']
    if not isinstance(size, list) or len(size) != 2 or any(type(v) is not int or not 1 <= v <= 32768 for v in size) or size[0] * size[1] > 67108864:
        raise ValueError('texture size must be two integer dimensions 1..32768, at most 64 Mi pixels')
    path = (spec_path.parent / raw).resolve()
    if not path.is_file():
        raise ValueError('texture must be an existing file: ' + str(path))
    suffix = path.suffix.lower()
    if suffix not in ('.png', '.jpg', '.jpeg'):
        raise ValueError('unsupported texture format; only PNG and JPEG are supported')
    with path.open('rb') as stream:
        header = stream.read(8)
    if not (header == b'\x89PNG\r\n\x1a\n' if suffix == '.png' else header.startswith(b'\xff\xd8\xff')):
        raise ValueError('texture file signature does not match PNG/JPEG suffix')
    if digest(path) != value['sha256']:
        raise ValueError('texture SHA-256 mismatch: ' + str(path))
    value['path'] = str(path)


def validate(spec, spec_path):
    keys(spec, ('schema_version', 'materials', 'bindings'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    for field, limit in (('materials', 64), ('bindings', 4096)):
        if not isinstance(spec[field], list) or not 1 <= len(spec[field]) <= limit:
            raise ValueError(field + ' must be a nonempty bounded list')
    names = set()
    for row in spec['materials']:
        keys(row, ('name', 'base_color', 'roughness', 'metallic'), ('uv_map', 'normal'))
        text(row['name'], 'material name')
        if row['name'] in names:
            raise ValueError('duplicate new material name')
        names.add(row['name'])
        textured = 'normal' in row or any(isinstance(row[field], dict) for field in ('base_color', 'roughness', 'metallic'))
        if textured:
            text(row.get('uv_map'), 'uv_map')
        elif 'uv_map' in row:
            raise ValueError('uv_map is only allowed with texture maps')
        if 'normal' in row:
            validate_map(row['normal'], spec_path, normal=True)
        for field in ('base_color', 'roughness', 'metallic'):
            value = row[field]
            if isinstance(value, dict):
                validate_map(value, spec_path)
            elif field == 'base_color':
                if not isinstance(value, list) or len(value) != 4:
                    raise ValueError('base_color requires four linear RGBA factors')
                for factor in value:
                    unit(factor, 'base_color factor')
            else:
                unit(value, field)
    for row in spec['bindings']:
        keys(row, ('object', 'material'), ('slot', 'append'))
        text(row['object'], 'object name')
        text(row['material'], 'binding material')
        if row['material'] not in names:
            raise ValueError('binding must reference an explicitly new material')
        if ('slot' in row) == ('append' in row):
            raise ValueError('binding requires exactly one explicit existing slot or append:true policy')
        if 'append' in row and row['append'] is not True:
            raise ValueError('append policy must be literal true')
        if 'slot' in row and (type(row['slot']) is not int or row['slot'] < 0):
            raise ValueError('slot must be an existing nonnegative integer index, not boolean')
    if {binding['material'] for binding in spec['bindings']} != names:
        raise ValueError('every new material must be explicitly bound to a target object/slot')
    return spec


def verify_texture_hashes(spec):
    for material in spec['materials']:
        for role in ('base_color', 'roughness', 'metallic', 'normal'):
            mapping = material.get(role)
            if isinstance(mapping, dict) and digest(mapping['path']) != mapping['sha256']:
                raise ValueError('texture SHA-256 changed during operation: ' + mapping['path'])


def preflight(spec):
    """Resolve the whole write scope before making any materials or slot edits."""
    import bpy
    verify_texture_hashes(spec)
    materials = {row['name']: row for row in spec['materials']}
    for name in materials:
        if name in bpy.data.materials:
            raise ValueError('material name is already owned; choose a NEW name: ' + name)
    used = set()
    for binding in spec['bindings']:
        matches = [obj for obj in bpy.data.objects if obj.name == binding['object']]
        if len(matches) != 1 or matches[0].type != 'MESH':
            raise ValueError('target must be an unambiguous exact named mesh object: ' + binding['object'])
        obj = matches[0]
        if any(block.library or block.override_library or not block.is_editable for block in (obj, obj.data)):
            raise ValueError('target object and mesh must be local, editable, non-overridden data: ' + obj.name)
        if 'append' in binding and obj.data.users != 1:
            raise ValueError('append would modify shared mesh slots; make mesh single-user explicitly first: ' + obj.name)
        slot = binding.get('slot', 'append')
        if slot != 'append' and slot >= len(obj.material_slots):
            raise ValueError('target slot index does not exist: ' + obj.name)
        key = (obj.name, slot)
        if key in used:
            raise ValueError('conflicting duplicate object/slot binding')
        used.add(key)
        material = materials[binding['material']]
        if 'uv_map' in material and material['uv_map'] not in obj.data.uv_layers:
            raise ValueError('target mesh lacks explicit UV map ' + material['uv_map'] + ': ' + obj.name)


def build(spec):
    import bpy
    preflight(spec)
    materials = []
    for row in spec['materials']:
        mat = bpy.data.materials.new(row['name'])
        if mat.node_tree is None:  # Blender <5 still needs the opt-in.
            mat.use_nodes = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        nodes.clear()
        shader = nodes.new('ShaderNodeBsdfPrincipled')
        output = nodes.new('ShaderNodeOutputMaterial')
        links.new(shader.outputs['BSDF'], output.inputs['Surface'])
        uv = nodes.new('ShaderNodeUVMap') if 'uv_map' in row else None
        if uv:
            uv.uv_map = row['uv_map']
        maps = []
        for role, socket in (('base_color', 'Base Color'), ('roughness', 'Roughness'), ('metallic', 'Metallic'), ('normal', 'Normal')):
            if role not in row:
                continue
            value = row[role]
            if not isinstance(value, dict):
                shader.inputs[socket].default_value = value
                if role == 'base_color':
                    shader.inputs['Alpha'].default_value = value[3]
                continue
            image = bpy.data.images.load(value['path'], check_existing=False)
            if list(image.size) != value['size'] or not image.has_data or image.source != 'FILE' or image.file_format not in ('PNG', 'JPEG') or len(image.pixels) != value['size'][0] * value['size'][1] * 4:
                bpy.data.images.remove(image)
                raise ValueError('texture failed decode or actual dimensions/format do not match: ' + value['path'])
            image.colorspace_settings.name = 'sRGB' if role == 'base_color' else 'Non-Color'
            if role in ('roughness', 'metallic'):
                import numpy as np
                pixels = np.empty(len(image.pixels), dtype=np.float32)
                image.pixels.foreach_get(pixels)
                rgb = pixels.reshape((-1, 4))[:, :3]
                if not np.isfinite(rgb).all() or np.max(np.abs(rgb[:, 1:] - rgb[:, :1])) > 1e-5:
                    bpy.data.images.remove(image)
                    raise ValueError('scalar roughness/metallic must be grayscale; packed/colored channels are unsupported')
            texture = nodes.new('ShaderNodeTexImage')
            texture.label = role
            texture.image = image
            texture.extension = 'REPEAT'
            texture.interpolation = 'Linear'
            links.new(uv.outputs['UV'], texture.inputs['Vector'])
            if role == 'base_color':
                links.new(texture.outputs['Color'], shader.inputs[socket])
                links.new(texture.outputs['Alpha'], shader.inputs['Alpha'])
            elif role == 'normal':
                normal_map = nodes.new('ShaderNodeNormalMap')
                normal_map.space = 'TANGENT'
                normal_map.uv_map = row['uv_map']
                normal_map.inputs['Strength'].default_value = 1
                color = texture.outputs['Color']
                if value['convention'] == 'DirectX':
                    separate = nodes.new('ShaderNodeSeparateColor')
                    separate.mode = 'RGB'
                    combine = nodes.new('ShaderNodeCombineColor')
                    combine.mode = 'RGB'
                    invert = nodes.new('ShaderNodeMath')
                    invert.operation = 'SUBTRACT'
                    invert.inputs[0].default_value = 1
                    links.new(color, separate.inputs['Color'])
                    links.new(separate.outputs['Green'], invert.inputs[1])
                    links.new(invert.outputs[0], combine.inputs['Green'])
                    for channel in ('Red', 'Blue'):
                        links.new(separate.outputs[channel], combine.inputs[channel])
                    color = combine.outputs['Color']
                links.new(color, normal_map.inputs['Color'])
                links.new(normal_map.outputs['Normal'], shader.inputs['Normal'])
            else:
                separate = nodes.new('ShaderNodeSeparateColor')
                separate.mode = 'RGB'
                links.new(texture.outputs['Color'], separate.inputs['Color'])
                links.new(separate.outputs['Red'], shader.inputs[socket])
            maps.append({'role': role, 'path': image.filepath, 'sha256': digest(image.filepath),
                         'size': list(image.size), 'colorspace': image.colorspace_settings.name})
            if role == 'normal':
                maps[-1]['normal_convention'] = value['convention']
        materials.append({'name': mat.name, 'representation': 'texture_backed' if maps else 'untextured_constants', 'maps': maps})
    bindings = []
    for row in spec['bindings']:
        obj = bpy.data.objects[row['object']]
        material = bpy.data.materials[row['material']]
        if 'append' in row:
            index = len(obj.material_slots)
            obj.data.materials.append(material)
        else:
            index = row['slot']
            slot = obj.material_slots[index]
            slot.link = 'OBJECT'
            slot.material = material
        bindings.append({'object': obj.name, 'material': material.name, 'slot': index,
                         'policy': 'append' if 'append' in row else 'existing_slot_object_override'})
    return {'materials': materials, 'bindings': bindings}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('source', 'spec', 'output', 'report'):
        parser.add_argument('--' + arg, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        check_paths(args)
        spec = validate(json.loads(args.spec.read_text(encoding='utf8'), object_pairs_hook=unique_object), args.spec)
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        lineage = {'source': str(args.source.resolve()), 'source_sha256': digest(args.source),
                   'spec': str(args.spec.resolve()), 'spec_sha256': digest(args.spec),
                   'blender_version': bpy.app.version_string}
        bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()), use_scripts=False)
        report = {'schema_version': 1, 'command': 'build-pbr', 'status': 'built', 'lineage': lineage, **build(spec)}
        if digest(args.source) != lineage['source_sha256']:
            raise ValueError('source changed during operation; refusing publication')
        if digest(args.spec) != lineage['spec_sha256']:
            raise ValueError('spec changed during operation; refusing publication')
        verify_texture_hashes(spec)
        save_snapshot(args, report)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError, ImportError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    cli = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(cli))
