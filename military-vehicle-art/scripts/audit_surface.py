"""Read-only evaluated-mesh surface diagnostics. See surface-audit.md."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import stat
import tempfile


def safe_path(raw):
    path_text(str(raw))
    path = Path(os.path.abspath(raw))
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ValueError('symlink path/component is unsupported: ' + str(path))
    return path


def guard_paths(source, spec_path, report_path, maps=()):
    base = [safe_path(p) for p in (source, spec_path)]
    output = safe_path(report_path)
    inputs = list(base)
    for path in maps:
        path = safe_path(path)
        if any(path == p or os.path.samefile(path, p) for p in base):
            raise ValueError('texture/input path alias')
        if path not in inputs:
            inputs.append(path)
    for i, first in enumerate(inputs):
        if not stat.S_ISREG(first.stat().st_mode):
            raise ValueError('inputs must be existing regular files')
        for second in inputs[i+1:]:
            if os.path.samefile(first, second):
                raise ValueError('input path aliases are forbidden')
        if output == first or (output.exists() and os.path.samefile(output, first)):
            raise ValueError('report/input path alias')
    if os.path.lexists(output):
        raise ValueError('report must be NEW, not an existing path')
    if not output.parent.is_dir():
        raise ValueError('report parent directory must already exist')
    if source.suffix.lower() != '.blend' or spec_path.suffix.lower() != '.json' or output.suffix.lower() != '.json':
        raise ValueError('expected .blend source and .json spec/report')
    return inputs


def verify_inputs(hashes):
    for path, expected in hashes.items():
        safe_path(path)
        if digest(path) != expected:
            raise ValueError('input SHA-256 changed during audit: ' + str(path))


def publish(path, report, verify):
    """Complete file + exclusive hard-link publication; never replace a winner."""
    data = (json.dumps(report, indent=2, allow_nan=False)+'\n').encode('utf-8')
    fd, temporary = tempfile.mkstemp(prefix='.surface-audit-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        verify()
        os.link(temporary, path, follow_symlinks=False)
    finally:
        Path(temporary).unlink(missing_ok=True)


def consume(spec, budget, field, amount):
    budget[field] += amount
    if budget[field] > spec['limits'][field]:
        raise ValueError(field + ' workload exceeded')


def keys(value, names):
    if type(value) is not dict or set(value) != set(names):
        raise ValueError('expected exactly fields: ' + ', '.join(names))


def bounded(value, label, low, high, integer=False):
    if (type(value) not in ((int,) if integer else (int, float))
            or not low <= value <= high):
        raise ValueError(f'{label} must be {"integer " if integer else "finite numeric "}{low}..{high}')
    return value


def text(value, label):
    if (type(value) is not str or not value.strip() or '\x00' in value
            or len(value.encode('utf-8')) > 63):
        raise ValueError(label + ' must be nonempty text, <=63 UTF-8 bytes')


def path_text(value):
    if (type(value) is not str or not value.strip() or '\x00' in value
            or len(value) > 4096 or '..' in Path(value).parts):
        raise ValueError('path must be explicit text without parent traversal')


def validate(spec):
    keys(spec, ('schema_version', 'meters_per_blender_unit', 'limits', 'overlap', 'seams', 'targets'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    bounded(spec['meters_per_blender_unit'], 'meters_per_blender_unit', 1e-9, 1e6)
    keys(spec['limits'], ('triangles', 'overlap_pairs', 'seam_samples'))
    for key, maximum in (('triangles', 20000), ('overlap_pairs', 2000000), ('seam_samples', 1000000)):
        bounded(spec['limits'][key], key, 1, maximum, integer=True)
    keys(spec['overlap'], ('scope', 'area_epsilon'))
    if spec['overlap']['scope'] != 'within_object_material_region':
        raise ValueError('only within_object_material_region overlap scope is supported')
    bounded(spec['overlap']['area_epsilon'], 'area_epsilon', 0, 1e-6)
    keys(spec['seams'], ('samples_per_edge', 'inset_fraction', 'discontinuity_threshold'))
    bounded(spec['seams']['samples_per_edge'], 'samples_per_edge', 1, 128, integer=True)
    bounded(spec['seams']['inset_fraction'], 'inset_fraction', 0, .01)
    bounded(spec['seams']['discontinuity_threshold'], 'discontinuity_threshold', 0, 1)
    if type(spec['targets']) is not list or not 1 <= len(spec['targets']) <= 16:
        raise ValueError('targets must contain 1..16 explicit objects')
    names, region_count = set(), 0
    for target in spec['targets']:
        keys(target, ('object', 'uv_map', 'regions'))
        text(target['object'], 'object')
        text(target['uv_map'], 'uv_map')
        if target['object'] in names:
            raise ValueError('duplicate target object')
        names.add(target['object'])
        if type(target['regions']) is not list or not 1 <= len(target['regions']) <= 16:
            raise ValueError('regions must contain 1..16 material regions')
        materials = set()
        region_count += len(target['regions'])
        if region_count > 64:
            raise ValueError('at most 64 regions total')
        for region in target['regions']:
            keys(region, ('material', 'uv_policy', 'texture'))
            text(region['material'], 'material')
            if region['material'] in materials:
                raise ValueError('duplicate material region')
            materials.add(region['material'])
            if region['uv_policy'] not in ('single_1001', 'repeat_unwrapped'):
                raise ValueError('uv_policy must be single_1001 or repeat_unwrapped; UDIM is unsupported')
            mapping = region['texture']
            keys(mapping, ('path', 'sha256', 'size', 'role', 'color_space', 'wrap'))
            path_text(mapping['path'])
            if type(mapping['sha256']) is not str or re.fullmatch('[0-9a-f]{64}', mapping['sha256']) is None:
                raise ValueError('sha256 requires 64 lowercase hexadecimal characters')
            size = mapping['size']
            if type(size) is not list or len(size) != 2:
                raise ValueError('size must be [width, height]')
            for v in size:
                bounded(v, 'texture dimension', 1, 16384, integer=True)
            if size[0]*size[1] > 16777216:
                raise ValueError('texture exceeds 16 Mi pixels')
            if mapping['role'] not in ('color', 'scalar', 'tangent_normal'):
                raise ValueError('role must be color, scalar or tangent_normal')
            spaces = ('srgb', 'linear') if mapping['role'] == 'color' else ('data',)
            if mapping['color_space'] not in spaces:
                raise ValueError('color_space is inconsistent with map role')
            if mapping['wrap'] not in ('clamp', 'repeat'):
                raise ValueError('wrap must be clamp or repeat')
            if region['uv_policy'] == 'repeat_unwrapped' and mapping['wrap'] != 'repeat':
                raise ValueError('repeat_unwrapped requires repeat wrapping')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def map_path(mapping, spec_path):
    return (spec_path.parent / mapping['path']).absolute()


def load_maps(spec, spec_path):
    from PIL import Image
    images, pixel_count = {}, 0
    for target in spec['targets']:
        for region in target['regions']:
            mapping = region['texture']
            path = map_path(mapping, spec_path)
            if digest(path) != mapping['sha256']:
                raise ValueError('texture SHA-256 mismatch: ' + str(path))
            expected = 'PNG' if path.suffix.lower() == '.png' else 'JPEG'
            if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
                raise ValueError('only PNG/JPEG maps are supported')
            if expected == 'PNG':
                with path.open('rb') as stream:
                    header = stream.read(25)
                if (len(header) != 25 or header[:8] != b'\x89PNG\r\n\x1a\n'
                        or header[12:16] != b'IHDR' or header[24] != 8):
                    raise ValueError('static 8-bit PNG maps required; no silent bit depth truncation')
            with Image.open(path) as image:
                if (image.format != expected or image.mode not in ('L', 'RGB', 'RGBA')
                        or getattr(image, 'n_frames', 1) != 1):
                    raise ValueError('unsupported texture format/signature/mode/animation; need static 8-bit L/RGB/RGBA')
                if list(image.size) != mapping['size']:
                    raise ValueError('texture actual dimensions mismatch')
                if path not in images:
                    pixel_count += image.width*image.height
                    if pixel_count > 67108864:
                        raise ValueError('total texture pixel workload exceeds 64 Mi pixels')
                    image.load()
                    images[path] = image.copy()
    return images


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def density(triangles):
    area = sum(t['world_area_m2'] for t in triangles)
    texels = sum(t['pixel_area'] for t in triangles)
    return {'status': 'measured', 'world_area_m2': area,
            'pixel_triangle_area_sum': texels,
            'effective_texels_per_meter': math.sqrt(texels / area),
            'triangles': [{'triangle': t['triangle'], 'polygon': t['polygon'],
                           'world_area_m2': t['world_area_m2'],
                           'uv_area': t['uv_area'], 'pixel_area': t['pixel_area'],
                           'texels_per_meter': math.sqrt(t['pixel_area'] / t['world_area_m2'])}
                          for t in triangles]}


def cross3(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def world_vectors(obj, mesh, indices):
    # Translation cancels analytically. Never subtract float32 world positions.
    points = [tuple(mesh.vertices[i].co) for i in indices]
    matrix = obj.matrix_world
    if any(not math.isfinite(v) for row in matrix for v in row):
        raise ValueError('nonfinite evaluated transform')
    result = [tuple(sum(float(matrix[i][j])*(p[j]-points[0][j]) for j in range(3))
                    for i in range(3)) for p in points]
    if any(not math.isfinite(v) or abs(v) > 1e15 for point in result for v in point):
        raise ValueError('world edge vector outside numeric implementation bounds +/-1e15 BU')
    return result


def mapping_stretch(xyz, uv, size, meters):
    """Singular values of the actual affine world-plane -> UV/pixel map."""
    e1, e2 = [tuple(v*meters for v in point) for point in xyz[1:]]
    x1 = math.hypot(*e1)
    x2 = sum(a*b for a, b in zip(e2, e1)) / x1
    y2 = math.hypot(*cross3(e1, e2)) / x1
    signed = ((uv[1][0]-uv[0][0])*(uv[2][1]-uv[0][1])
              -(uv[1][1]-uv[0][1])*(uv[2][0]-uv[0][0]))
    def singular(scale):
        du = [(uv[1][i]-uv[0][i])*scale[i] for i in (0, 1)]
        dv = [(uv[2][i]-uv[0][i])*scale[i] for i in (0, 1)]
        a, c = du[0]/x1, du[1]/x1
        b, d = (dv[0]-a*x2)/y2, (dv[1]-c*x2)/y2
        trace = a*a+b*b+c*c+d*d
        # det(UV * inverse(world_basis)) = oriented UV area / basis area.
        # Re-subtracting the rounded Jacobian columns can erase thin valid UVs.
        det = signed*scale[0]*scale[1]/(x1*y2)
        high = math.sqrt((trace + math.sqrt(max(0, trace*trace-4*det*det))) / 2)
        low = abs(det)/high
        return [high, low]
    normalized = singular((1, 1))
    texels = singular(size)
    return {'uv_singular_values_per_meter': normalized,
            'texel_singular_values_per_meter': texels,
            'uv_anisotropy': normalized[0]/normalized[1],
            'texel_anisotropy': texels[0]/texels[1], 'uv_mirrored': signed < 0}


def cross2(a, b, p):
    return (b[0]-a[0])*(p[1]-a[1]) - (b[1]-a[1])*(p[0]-a[0])


def intersection_area(subject, clip):
    """Convex polygon clipping, not a raster, island sum or packing proxy."""
    polygon = list(subject)
    clip = list(clip)
    if cross2(*clip) < 0:
        clip.reverse()
    for a, b in zip(clip, clip[1:]+clip[:1]):
        source, polygon = polygon, []
        if not source:
            break
        start = source[-1]
        ds = cross2(a, b, start)
        for end in source:
            de = cross2(a, b, end)
            if (ds >= 0) != (de >= 0):
                fraction = ds/(ds-de)
                polygon.append(tuple(start[i]+fraction*(end[i]-start[i]) for i in (0, 1)))
            if de >= 0:
                polygon.append(end)
            start, ds = end, de
    if len(polygon) < 3:
        return 0.0
    # Fan around the first point avoids cancellation for translated UVs.
    return abs(sum(cross2(polygon[0], polygon[i], polygon[i+1])
                   for i in range(1, len(polygon)-1))) / 2


def overlap(triangles, spec, budget):
    pairs = len(triangles)*(len(triangles)-1)//2
    consume(spec, budget, 'overlap_pairs', pairs)
    epsilon = spec['overlap']['area_epsilon']
    count, area_sum, candidates = 0, 0.0, 0
    records = []
    for i, first in enumerate(triangles):
        for second in triangles[i+1:]:
            a, b = first['uv'], second['uv']
            if any(max(p[k] for p in a) <= min(p[k] for p in b)
                   or max(p[k] for p in b) <= min(p[k] for p in a) for k in (0, 1)):
                continue
            candidates += 1
            area = intersection_area(a, b)
            if area > epsilon:
                count += 1
                area_sum += area
                if len(records) < 256:
                    records.append({'triangles': [first['triangle'], second['triangle']],
                                    'intersection_area_uv2': area})
    return {'status': 'measured' if pairs else 'not_applicable_single_triangle',
            'method': 'convex_triangle_clipping_float64',
            'scope': spec['overlap']['scope'], 'area_epsilon_uv2': epsilon,
            'triangle_pairs': pairs, 'aabb_candidates': candidates,
            'positive_area_pairs': count, 'pairwise_intersection_area_sum_uv2': area_sum,
            'intersections': records, 'intersections_omitted': count-len(records),
            'record_limit': 256}


def pixel_sample(image, uv, mapping):
    """Bilinear normalized bottom-left UV; decode sRGB BEFORE filtering."""
    width, height = image.size
    x, y = uv[0]*width-0.5, (1-uv[1])*height-0.5
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x-ix, y-iy
    channels = 1 if mapping['role'] == 'scalar' else 3
    result = [0.0]*channels
    for dx, dy, weight in ((0, 0, (1-fx)*(1-fy)), (1, 0, fx*(1-fy)),
                           (0, 1, (1-fx)*fy), (1, 1, fx*fy)):
        px, py = ix+dx, iy+dy
        if mapping['wrap'] == 'repeat':
            px, py = px % width, py % height
        else:
            px, py = min(width-1, max(0, px)), min(height-1, max(0, py))
        values = image.getpixel((px, py))
        if not isinstance(values, tuple):
            values = (values, values, values)
        for c in range(channels):
            value = values[c]/255
            if mapping['color_space'] == 'srgb':
                value = value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4
            result[c] += value*weight
    return result


def seam_edges(mesh, uv, obj):
    anchors = {}
    for tri in mesh.loop_triangles:
        center = tuple(sum(uv.data[l].uv[i] for l in tri.loops)/3 for i in (0, 1))
        vertices = list(tri.vertices)
        for a, b in zip(vertices, vertices[1:]+vertices[:1]):
            anchors[(tri.polygon_index, tuple(sorted((a, b))))] = center
    edges = {}
    for face in mesh.polygons:
        material = (obj.material_slots[face.material_index].material
                    if face.material_index < len(obj.material_slots) else None)
        loops = list(face.loop_indices)
        for i, first in enumerate(loops):
            second = loops[(i+1) % len(loops)]
            a, b = mesh.loops[first].vertex_index, mesh.loops[second].vertex_index
            points = (tuple(uv.data[first].uv), tuple(uv.data[second].uv))
            if a > b:
                points = points[::-1]
            edges.setdefault(mesh.loops[first].edge_index, []).append({
                'material': material.name if material else None, 'uv': points,
                'anchor': anchors[(face.index, tuple(sorted((a, b))))]})
    return edges


def seams(mesh, obj, edge_uses, region, image, spec, budget):
    mapping, controls = region['texture'], spec['seams']
    n, inset = controls['samples_per_edge'], controls['inset_fraction']
    selected, boundaries, nonmanifold, open_edges = [], 0, 0, 0
    for index, uses in edge_uses.items():
        if not any(use['material'] == region['material'] for use in uses):
            continue
        if len(uses) == 1:
            open_edges += 1
        elif len(uses) != 2:
            nonmanifold += 1
        elif any(use['material'] != region['material'] for use in uses):
            boundaries += 1
        elif any(abs(a-b) > 1e-7 for p, q in zip(uses[0]['uv'], uses[1]['uv'])
                 for a, b in zip(p, q)):
            selected.append((index, uses))
    normal = mapping['role'] == 'tangent_normal'
    count = 0 if normal else len(selected)*n
    consume(spec, budget, 'seam_samples', count)
    status = ('unsupported_tangent_normal' if normal else
              'sampled' if selected else 'not_applicable_no_uv_split_edges')
    if nonmanifold and not normal:
        status = 'partial_nonmanifold_edges' if selected else 'unsupported_nonmanifold_edges'
    records, maximum, total, discontinuous, max_spacing = [], 0.0, 0.0, 0, 0.0
    for index, uses in ([] if normal else selected):
        deltas = []
        for k in range(n):
            t = (k+0.5)/n
            samples = []
            for use in uses:
                point = tuple((1-inset)*(use['uv'][0][i]*(1-t)+use['uv'][1][i]*t)
                              +inset*use['anchor'][i] for i in (0, 1))
                samples.append(pixel_sample(image, point, mapping))
            deltas.append(max(abs(a-b) for a, b in zip(*samples)))
        peak = max(deltas)
        maximum, total = max(maximum, peak), total+sum(deltas)
        discontinuous += peak > controls['discontinuity_threshold']
        edge = mesh.edges[index]
        xyz = world_vectors(obj, mesh, edge.vertices)
        spacing = math.hypot(*xyz[1])*spec['meters_per_blender_unit']*(1-inset)/n
        max_spacing = max(max_spacing, spacing)
        pixel_spacing = [math.hypot(*[(use['uv'][1][i]-use['uv'][0][i])*
                                     mapping['size'][i]*(1-inset)/n for i in (0, 1)])
                         for use in uses]
        if len(records) < 256:
            records.append({'edge': index, 'max_delta': peak, 'mean_delta': sum(deltas)/n,
                            'world_sample_spacing_m': spacing,
                            'pixel_sample_spacing': pixel_spacing})
    return {'status': status, 'uv_split_edges': len(selected), 'sample_count': count,
            'samples_per_edge': n, 'inset_fraction': inset,
            'uv_endpoint_tolerance': 1e-7, 'sampling': 'edge_midpoint_strata_bilinear',
            'endpoints_sampled': False, 'alpha_compared': False,
            'comparison_space': ('unsupported' if normal else 'linear_rgb'
                                  if mapping['role'] == 'color' else 'data_red'),
            'excluded_material_boundaries': boundaries, 'excluded_open_edges': open_edges,
            'excluded_nonmanifold_edges': nonmanifold,
            'discontinuity_threshold': controls['discontinuity_threshold'],
            'discontinuous_edges': discontinuous if count else None,
            'max_delta': maximum if count else None, 'mean_delta': total/count if count else None,
            'max_world_sample_spacing_m': max_spacing if count else None,
            'edges': records, 'edges_omitted': (0 if normal else len(selected))-len(records),
            'record_limit': 256}


def audit(spec, spec_path, images):
    import bpy
    targets = []
    budget = {'triangles': 0, 'overlap_pairs': 0, 'seam_samples': 0}
    bpy.context.view_layer.update()
    graph = bpy.context.evaluated_depsgraph_get()
    for target in spec['targets']:
        original = bpy.data.objects.get(target['object'])
        if original is None or original.type != 'MESH' or original.name not in bpy.context.view_layer.objects:
            raise ValueError('target must be a named MESH in the active view layer')
        obj = original.evaluated_get(graph)
        mesh = obj.to_mesh(preserve_all_data_layers=True, depsgraph=graph)
        try:
            mesh.calc_loop_triangles()
            consume(spec, budget, 'triangles', len(mesh.loop_triangles))
            if not mesh.loop_triangles:
                raise ValueError('empty evaluated triangle mesh')
            uv = mesh.uv_layers[target['uv_map']]
            if any(not math.isfinite(v) or abs(v) > 1e6 for item in uv.data for v in item.uv):
                raise ValueError('nonfinite UV or UV coordinate outside implementation bounds +/-1e6')
            edge_uses = seam_edges(mesh, uv, obj)
            regions = []
            all_triangles = []
            for region in target['regions']:
                mapping = region['texture']
                path = map_path(mapping, spec_path)
                pixels = images[path]
                size = list(pixels.size)
                triangles = []
                for tri in mesh.loop_triangles:
                    material = (obj.material_slots[tri.material_index].material
                                if tri.material_index < len(obj.material_slots) else None)
                    if not material or material.name != region['material']:
                        continue
                    xyz = world_vectors(obj, mesh, tri.vertices)
                    points = [tuple(uv.data[i].uv) for i in tri.loops]
                    a, b, c = points
                    uv_area = abs((b[0]-a[0])*(c[1]-a[1]) - (b[1]-a[1])*(c[0]-a[0])) / 2
                    area = math.hypot(*cross3(xyz[1], xyz[2])) / 2
                    area *= spec['meters_per_blender_unit'] ** 2
                    if not math.isfinite(area) or not math.isfinite(uv_area) or area <= 1e-20 or uv_area <= 1e-20:
                        raise ValueError('degenerate world/UV triangle')
                    triangles.append({'triangle': tri.index, 'polygon': tri.polygon_index,
                                      'world_area_m2': area, 'uv_area': uv_area, 'uv': points,
                                      'pixel_area': uv_area * size[0] * size[1],
                                      'stretch': mapping_stretch(xyz, points, size,
                                                        spec['meters_per_blender_unit'])})
                if not triangles:
                    raise ValueError('empty declared material region')
                points = [p for tri in triangles for p in tri['uv']]
                bounds = [[min(p[i] for p in points) for i in (0, 1)],
                          [max(p[i] for p in points) for i in (0, 1)]]
                outside = any(v < 0 or v > 1 for p in points for v in p)
                unsupported = {'status': 'unsupported_outside_1001',
                               'reason': 'declared single_1001 domain excludes some UV coordinates'}
                blocked = outside and region['uv_policy'] == 'single_1001'
                if blocked:
                    measurements = {name: dict(unsupported) for name in ('density', 'stretch', 'overlap', 'seams')}
                else:
                    measurements = {
                        'density': density(triangles),
                        'stretch': {'status': 'measured', 'triangles': [
                            {'triangle': t['triangle'], 'polygon': t['polygon'], **t['stretch']}
                            for t in triangles]},
                        'overlap': ({'status': 'unsupported_periodic_domain',
                                     'reason': 'periodic folding/inter-tile copies are not intersected',
                                     'periodic_overlap_tested': False} if outside else overlap(triangles, spec, budget)),
                        'seams': seams(mesh, obj, edge_uses, region, pixels, spec, budget)}
                    all_triangles.extend(triangles)
                regions.append({'material': region['material'], 'uv_policy': region['uv_policy'],
                                'uv_bounds': bounds, 'outside_1001': outside,
                                'triangle_count': len(triangles),
                                'texture': {'path': str(path), 'sha256': mapping['sha256'],
                                            'actual_size': size, 'role': mapping['role'],
                                            'color_space': mapping['color_space'], 'wrap': mapping['wrap']},
                                **measurements})
            complete = all(r['density']['status'] == 'measured' for r in regions)
            targets.append({'object': obj.name, 'uv_map': target['uv_map'],
                            'evaluated_triangles': len(mesh.loop_triangles),
                            'audited_triangles': sum(r['triangle_count'] for r in regions),
                            'density': (density(all_triangles) if complete else
                                        {'status': 'unsupported_incomplete_regions'}), 'regions': regions})
        finally:
            obj.to_mesh_clear()
    return targets, budget


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True)
    parser.add_argument('--spec', required=True)
    parser.add_argument('--report', required=True)
    args = parser.parse_args(argv)
    try:
        source, spec_path, report_path = [safe_path(p) for p in (args.source, args.spec, args.report)]
        guard_paths(source, spec_path, report_path)
        if spec_path.stat().st_size > 1048576:
            raise ValueError('spec exceeds 1 MiB')
        spec_bytes = spec_path.read_bytes()
        spec = json.loads(spec_bytes, object_pairs_hook=unique_object)
        validate(spec)
        mappings = [r['texture'] for t in spec['targets'] for r in t['regions']]
        map_paths = [map_path(m, spec_path) for m in mappings]
        guard_paths(source, spec_path, report_path, map_paths)
        source_hash = digest(source)
        spec_hash = hashlib.sha256(spec_bytes).hexdigest()
        hashes = {source: source_hash, spec_path: spec_hash}
        for mapping, path in zip(mappings, map_paths):
            if path in hashes and hashes[path] != mapping['sha256']:
                raise ValueError('inconsistent declarations for the same map path')
            hashes[path] = mapping['sha256']
        images = load_maps(spec, spec_path)
        verify_inputs(hashes)
        import bpy
        bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
        targets, workload = audit(spec, spec_path, images)
        report = {'schema_version': 1, 'command': 'audit-surface', 'status': 'diagnostic',
                  'source': str(source), 'source_sha256': source_hash, 'spec_sha256': spec_hash,
                  'meters_per_blender_unit': spec['meters_per_blender_unit'],
                  'blender_version': bpy.app.version_string,
                  'scene_frame': bpy.context.scene.frame_current,
                  'scene_unit_scale_informational': bpy.context.scene.unit_settings.scale_length,
                  'units_policy': 'explicit_spec_scale_after_evaluated_world_transform',
                  'shader_graph_equivalence_verified': False, 'input_files_rehashed': True,
                  'workload': workload, 'limits': spec['limits'], 'targets': targets}
        def verify():
            guard_paths(source, spec_path, report_path, map_paths)
            verify_inputs(hashes)
        publish(report_path, report, verify)
        return 0
    except (ValueError, OSError, KeyError, TypeError, RuntimeError, OverflowError, ZeroDivisionError) as exc:
        print('audit-surface: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    args = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None
    raise SystemExit(main(args))
