"""Bounded revolved profiles and sampled round tubes in a NEW source snapshot.

See references/component-builders.md for supported domains and evidence limits.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reconstruct_vehicle import check_paths, digest, float32, keys, number, save_snapshot, text


def bounded(value, label, low, high):
    result = number(value, label)
    if not low <= result <= high:
        raise ValueError(f'{label} must be in [{low}, {high}]')
    return result


def vector(value, label):
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(label + ' must contain three numbers')
    return [bounded(v, label, -10000, 10000) for v in value]


def validate_profile(profile, mode):
    if mode == 'open_surface':
        if any(r <= 0 for r, _ in profile) or any(b[1]-a[1] < 1e-4 for a, b in zip(profile, profile[1:])):
            raise ValueError('open_surface needs positive radii and strictly increasing Z (step >= 0.0001)')
        return
    if len(profile) < 3:
        raise ValueError('closed_solid needs at least three samples; do not repeat the first')
    axis = [i for i, p in enumerate(profile) if p[0] == 0]
    if axis and (axis != [0, len(profile)-1] or profile[-1][1]-profile[0][1] < 1e-4):
        raise ValueError('axis contact requires only first/last samples on axis, ordered bottom to top')
    span = max(max(p[k] for p in profile)-min(p[k] for p in profile) for k in (0, 1))
    tolerance = max(1e-5, span*1e-7)
    def cross(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    def on(a, b, c):
        return all(min(a[k], b[k])-tolerance <= c[k] <= max(a[k], b[k])+tolerance for k in (0, 1))
    n = len(profile)
    edges = list(zip(profile, profile[1:]+profile[:1]))
    for i, (a, b) in enumerate(edges):
        if math.dist(a, b) < 1e-4:
            raise ValueError('collapsed profile edge (minimum 0.0001)')
        c = profile[(i+2) % n]
        if abs(cross(a, b, c)) <= tolerance**2 and sum((b[k]-a[k])*(c[k]-b[k]) for k in (0, 1)) <= 0:
            raise ValueError('profile reversal or overlapping adjacent edges')
        for j in range(i+1, n):
            if j in ((i+1) % n, (i-1) % n):
                continue
            c, d = edges[j]
            u, v, w, t = cross(a,b,c), cross(a,b,d), cross(c,d,a), cross(c,d,b)
            eps = tolerance*max(math.dist(a,b), math.dist(c,d))
            if (u*v < 0 and w*t < 0) or any(abs(q) <= eps and on(e,f,g) for q,e,f,g in ((u,a,b,c),(v,a,b,d),(w,c,d,a),(t,c,d,b))):
                raise ValueError('crossing/touching or numerically unsafe profile')
    # Shift before shoelace to avoid cancellation for translated Z values.
    z0 = profile[0][1]
    area2 = sum(a[0]*(b[1]-z0)-b[0]*(a[1]-z0) for a, b in edges)
    if area2 <= tolerance*tolerance:
        raise ValueError('closed profile must have positive area and counterclockwise radius/Z winding')


def sub(a, b):
    return tuple(x-y for x, y in zip(a, b))


def dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def segment_distance(a, b, c, d):
    """Closest distance of finite line segments, not swept-mesh collision."""
    u, v, w = sub(b,a), sub(d,c), sub(a,c)
    def cross(x, y):
        return (x[1]*y[2]-x[2]*y[1], x[2]*y[0]-x[0]*y[2], x[0]*y[1]-x[1]*y[0])
    def point_edge(p, x, y):
        edge = sub(y,x)
        t = min(1.0, max(0.0, dot(sub(p,x), edge)/dot(edge,edge)))
        return math.dist(p, tuple(x[k]+t*edge[k] for k in range(3)))
    values = [point_edge(a,c,d), point_edge(b,c,d), point_edge(c,a,b), point_edge(d,a,b)]
    normal = cross(u, v)
    denominator = dot(normal, normal)
    if denominator > 0:
        s, t = dot(cross(v,w), normal)/denominator, dot(cross(u,w), normal)/denominator
        if 0 <= s <= 1 and 0 <= t <= 1:
            values.append(math.dist(tuple(a[k]+s*u[k] for k in range(3)), tuple(c[k]+t*v[k] for k in range(3))))
    return min(values)


def validate_path(path, radius, up):
    lengths = [math.dist(a,b) for a,b in zip(path,path[1:])]
    if min(lengths) < max(1e-4, 4*radius):
        raise ValueError('tube steps must be >= 0.0001 and at least four radii; collapsed/dense paths are unsupported')
    directions = [tuple(v/length for v in sub(b,a)) for a,b,length in zip(path,path[1:],lengths)]
    if any(dot(a,b) < math.cos(math.pi/4)-1e-12 for a,b in zip(directions,directions[1:])):
        raise ValueError('tube direction changes must be at most 45 degrees; reversals are unsupported')
    up_length = math.sqrt(dot(up, up))
    if up_length < 1e-4 or abs(dot(up, directions[0]))/up_length > math.sqrt(.99):
        raise ValueError('frame_up needs length >= 0.0001 and perpendicular component >= 10 percent')
    edges = list(zip(path,path[1:]))
    for i, (a,b) in enumerate(edges):
        for c,d in edges[i+2:]:
            if segment_distance(a,b,c,d) <= 2.2*radius:
                raise ValueError('nonadjacent centerline segments are too close (must exceed 2.2 radii); no collision certification')


def validate(spec):
    keys(spec, ('schema_version', 'collection', 'components'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    text(spec['collection'], 'new collection')
    if not isinstance(spec['components'], list) or not 1 <= len(spec['components']) <= 32:
        raise ValueError('components must contain 1..32 builders')
    total = 0
    names = {'object_name': set(), 'mesh_name': set()}
    for row in spec['components']:
        if not isinstance(row, dict) or row.get('kind') not in ('lathe', 'tube'):
            raise ValueError('kind must be lathe or tube')
        common = ('kind', 'object_name', 'mesh_name', 'origin', 'segments')
        extra = ('mode', 'profile', 'smooth_angle_degrees') if row['kind'] == 'lathe' else ('radius', 'path', 'frame_up', 'caps')
        keys(row, common + extra)
        for name in ('object_name', 'mesh_name'):
            text(row[name], 'new ' + name)
            if row[name] in names[name]:
                raise ValueError('duplicate new ' + name)
            names[name].add(row[name])
        vector(row['origin'], 'origin')
        if type(row['segments']) is not int or not 8 <= row['segments'] <= 128:
            raise ValueError('segments must be integer 8..128')
        if row['kind'] == 'tube':
            radius = bounded(row['radius'], 'tube radius', 1e-4, 1000)
            if row['caps'] not in ('none', 'flat'):
                raise ValueError('tube caps must be none or flat')
            up = vector(row['frame_up'], 'frame_up')
            path = row['path']
            if not isinstance(path, list) or not 2 <= len(path) <= 512:
                raise ValueError('path needs 2..512 explicitly sampled XYZ points')
            for point in path:
                vector(point, 'path sample')
            validate_path(path, radius, up)
            validate_path([[float32(v) for v in p] for p in path], radius, up)
            total += len(row['path'])*row['segments']
            if total > 250000:
                raise ValueError('combined ring workload must be at most 250000 samples')
            continue
        if row['mode'] not in ('open_surface', 'closed_solid'):
            raise ValueError('lathe mode must be open_surface or closed_solid')
        bounded(row['smooth_angle_degrees'], 'smooth_angle_degrees', 1, 180)
        profile = row['profile']
        if not isinstance(profile, list) or not 2 <= len(profile) <= 512:
            raise ValueError('profile must contain 2..512 radius/Z samples')
        for point in profile:
            if not isinstance(point, list) or len(point) != 2:
                raise ValueError('profile sample must contain radius and Z')
            radius = bounded(point[0], 'profile radius', 0, 1000)
            if 0 < radius < 1e-4:
                raise ValueError('nonzero radius must be at least 0.0001')
            bounded(point[1], 'profile Z', -10000, 10000)
        validate_profile(profile, row['mode'])
        validate_profile([[float32(v) for v in p] for p in profile], row['mode'])
        total += len(profile)*row['segments']
        if total > 250000:
            raise ValueError('combined ring workload must be at most 250000 samples')
    return spec


def revolved(row):
    segments = row['segments']
    profile = row['profile']
    closed = row['mode'] == 'closed_solid'
    walked = profile + profile[:1] if closed else profile
    lengths = [0.0]
    for a, b in zip(walked, walked[1:]):
        lengths.append(lengths[-1] + math.dist(a, b))
    vertices, rings = [], []
    for r, z in profile:
        ring = []
        for j in range(segments if r else 1):
            ring.append(len(vertices))
            vertices.append((r*math.cos(2*math.pi*j/segments), r*math.sin(2*math.pi*j/segments), z))
        rings.append(ring)
    faces, uvs = [], []
    for i in range(len(walked)-1):
        a, b = rings[i], rings[(i+1) % len(profile)]
        if len(a) == len(b) == 1:
            continue  # The axis edge sweeps no surface.
        v0, v1 = lengths[i]/lengths[-1], lengths[i+1]/lengths[-1]
        for j in range(segments):
            k = (j+1) % segments
            u0, u1, um = j/segments, (j+1)/segments, (j+.5)/segments
            if len(a) == 1:
                faces.append((a[0], b[k], b[j]))
                uvs.append(((um, v0), (u1, v1), (u0, v1)))
            elif len(b) == 1:
                faces.append((a[j], a[k], b[0]))
                uvs.append(((u0, v0), (u1, v0), (um, v1)))
            else:
                faces.append((a[j], a[k], b[k], b[j]))
                uvs.append(((u0, v0), (u1, v0), (u1, v1), (u0, v1)))
    return vertices, faces, uvs


def routed(row):
    from mathutils import Vector
    path = [Vector(p) for p in row['path']]
    directions = [(b-a).normalized() for a, b in zip(path, path[1:])]
    tangents = [directions[0]]+[(a+b).normalized() for a, b in zip(directions, directions[1:])]+[directions[-1]]
    tangent = tangents[0]
    normal = Vector(row['frame_up'])
    normal = (normal-tangent*normal.dot(tangent)).normalized()
    segments, radius = row['segments'], row['radius']
    vertices = []
    for p, current in zip(path, tangents):
        normal = tangent.rotation_difference(current) @ normal
        normal = (normal-current*normal.dot(current)).normalized()
        binormal = current.cross(normal).normalized()
        vertices.extend(tuple(p+radius*(math.cos(2*math.pi*j/segments)*normal + math.sin(2*math.pi*j/segments)*binormal))
                        for j in range(segments))
        tangent = current
    lengths = [0.0]
    for a, b in zip(path, path[1:]):
        lengths.append(lengths[-1]+(b-a).length)
    faces, uvs = [], []
    for i in range(len(path)-1):
        for j in range(segments):
            k = (j+1) % segments
            faces.append((i*segments+j, i*segments+k, (i+1)*segments+k, (i+1)*segments+j))
            uvs.append(((j/segments, lengths[i]/lengths[-1]), ((j+1)/segments, lengths[i]/lengths[-1]),
                        ((j+1)/segments, lengths[i+1]/lengths[-1]), (j/segments, lengths[i+1]/lengths[-1])))
    if row['caps'] == 'flat':
        for end, center in enumerate((path[0], path[-1])):
            pole = len(vertices)
            vertices.append(tuple(center))
            ring = (len(path)-1)*segments if end else 0
            for j in range(segments):
                k = (j+1) % segments
                indices = (k, j) if not end else (j, k)
                faces.append((pole, ring+indices[0], ring+indices[1]))
                cx = 1.5+end
                uvs.append(((cx, .5), *[(cx+.4*math.cos(2*math.pi*q/segments), .5+.4*math.sin(2*math.pi*q/segments)) for q in indices]))
    return vertices, faces, uvs


def fill_mesh(mesh, row, geometry):
    vertices, faces, uvs = geometry
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    layer = mesh.uv_layers.new(name='ComponentUV')
    for face, coords in zip(mesh.polygons, uvs):
        for loop, uv in zip(face.loop_indices, coords):
            layer.data[loop].uv = uv
    uses = {}
    for face in mesh.polygons:
        for loop in face.loop_indices:
            nxt = face.loop_start + (loop-face.loop_start+1) % face.loop_total
            a, b = mesh.loops[loop].vertex_index, mesh.loops[nxt].vertex_index
            coords = (tuple(layer.data[loop].uv), tuple(layer.data[nxt].uv))
            uses.setdefault(mesh.loops[loop].edge_index, []).append(coords if a < b else coords[::-1])
    for edge in mesh.edges:
        adjacent = uses[edge.index]
        edge.use_seam = len(adjacent) == 1 or adjacent[0] != adjacent[1]
    mesh.set_sharp_from_angle(angle=math.radians(row['smooth_angle_degrees'] if row['kind'] == 'lathe' else 60))
    if row['kind'] == 'tube':
        for face in mesh.polygons[(len(row['path'])-1)*row['segments']:]:
            face.use_smooth = False


def mesh_evidence(mesh, closed, segments, world_matrix=None):
    """Actual float32 mesh mechanics; explicitly not self-intersection detection."""
    import bmesh
    mesh.calc_loop_triangles()
    area = [triangle.area for triangle in mesh.loop_triangles]
    world = [world_matrix @ v.co if world_matrix is not None else v.co.copy() for v in mesh.vertices]
    world_area = []
    for triangle in mesh.loop_triangles:
        a, b, c = [world[i] for i in triangle.vertices]
        u, v = sub(b, a), sub(c, a)
        world_area.append(math.hypot(u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2],
                                     u[0]*v[1]-u[1]*v[0])/2)
    if not world_area or not all(math.isfinite(a) and a > 1e-16 for a in world_area):
        raise ValueError('generated world mesh has collapsed/nonfinite triangles (minimum area > 1e-16); recenter or increase dimensions')
    uv = mesh.uv_layers['ComponentUV']
    uv_area = []
    for triangle in mesh.loop_triangles:
        a, b, c = [uv.data[i].uv for i in triangle.loops]
        uv_area.append(abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x))/2)
    if not area or not all(math.isfinite(a) and a > 1e-16 for a in area):
        raise ValueError('generated mesh has collapsed/nonfinite triangles (minimum area > 1e-16)')
    if not all(math.isfinite(a) and a > 1e-12 for a in uv_area):
        raise ValueError('generated UV triangle area must exceed 1e-12')
    if any(not math.isfinite(v) for face in mesh.polygons for v in face.normal):
        raise ValueError('generated mesh has nonfinite normals')
    bm = bmesh.new()
    try:
        bm.from_mesh(mesh)
        boundary = sum(e.is_boundary for e in bm.edges)
        consistent = all(e.is_contiguous for e in bm.edges if e.is_manifold)
        if any(len(e.link_faces) not in (1,2) for e in bm.edges) or not consistent or boundary != (0 if closed else 2*segments):
            raise ValueError('generated topology has unexpected boundary, nonmanifold edges or inconsistent winding')
        def centered_volume(coords):
            # Subtract AFTER the actual float32 transform, retaining BMesh's
            # volume convention for nonplanar quads without translation loss.
            center = coords[0]
            for vertex, point in zip(bm.verts, coords):
                vertex.co = sub(point, center)
            bm.normal_update()
            return bm.calc_volume(signed=True)
        volume = centered_volume([v.co for v in mesh.vertices]) if closed else None
        if closed and (not math.isfinite(volume) or volume <= 1e-12):
            raise ValueError('closed generated mesh needs positive signed volume > 1e-12')
        world_volume = centered_volume(world) if closed else None
        if closed and (not math.isfinite(world_volume) or world_volume <= 1e-12):
            raise ValueError('closed generated world mesh needs positive signed volume > 1e-12; recenter or increase dimensions')
    finally:
        bm.free()
    return {'closed': closed, 'vertices': len(mesh.vertices), 'edges': len(mesh.edges), 'faces': len(mesh.polygons),
            'boundary_edges': boundary, 'winding_consistent': consistent, 'signed_volume': volume,
            'world_signed_volume': world_volume,
            'uv_name': uv.name, 'seam_edges': sum(edge.use_seam for edge in mesh.edges),
            'minimum_triangle_area': min(area), 'minimum_world_triangle_area': min(world_area),
            'minimum_uv_triangle_area': min(uv_area)}


def build(spec):
    import bpy
    from mathutils import Matrix
    validate(spec)
    if bpy.context.mode != 'OBJECT' or any(mesh.is_editmode for mesh in bpy.data.meshes):
        raise ValueError('component construction requires an Object-mode source')
    if spec['collection'] in bpy.data.collections or any(scene.collection.name == spec['collection'] for scene in bpy.data.scenes):
        raise ValueError('new collection name is already owned')
    for row in spec['components']:
        if row['object_name'] in bpy.data.objects or row['mesh_name'] in bpy.data.meshes:
            raise ValueError('new object/mesh name is already owned: ' + row['object_name'])
    prepared = []
    for row in spec['components']:
        geometry = revolved(row) if row['kind'] == 'lathe' else routed(row)
        vertices = geometry[0]
        local = [tuple(float32(v) for v in p) for p in vertices]
        world = [tuple(float32(p[k]+float32(row['origin'][k])) for k in range(3)) for p in local]
        if len(set(local)) != len(vertices) or len(set(world)) != len(vertices):
            raise ValueError('generated vertices collapse at Blender float32 local/world precision; recenter or increase dimensions')
        prepared.append(geometry)
    meshes, objects, reports = [], [], []
    collection = None
    try:
        for row, geometry in zip(spec['components'], prepared):
            mesh = bpy.data.meshes.new(row['mesh_name'])
            meshes.append(mesh)
            fill_mesh(mesh, row, geometry)
            closed = row['mode'] == 'closed_solid' if row['kind'] == 'lathe' else row['caps'] == 'flat'
            reports.append({'object': row['object_name'], 'mesh': mesh.name, 'kind': row['kind'],
                            **mesh_evidence(mesh, closed, row['segments'], Matrix.Translation(row['origin'])),
                            'frame_method': 'parallel_transport_bisector_tangents' if row['kind'] == 'tube' else None})
        collection = bpy.data.collections.new(spec['collection'])
        bpy.context.scene.collection.children.link(collection)
        for row, mesh in zip(spec['components'], meshes):
            obj = bpy.data.objects.new(row['object_name'], mesh)
            objects.append(obj)
            obj.location = row['origin']
            collection.objects.link(obj)
    except BaseException:
        for obj in objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        if collection is not None:
            bpy.data.collections.remove(collection, do_unlink=True)
        for mesh in meshes:
            bpy.data.meshes.remove(mesh, do_unlink=True)
        raise
    return {'collection': collection.name, 'components': reports, 'self_intersection_tested': False,
            'collision_with_scene_tested': False, 'physical_engineering_validated': False,
            'uv_overlap_tested': False, 'texel_density_tested': False,
            'limitations': 'Mechanics only, not artistic approval, swept-mesh self-intersection/collision certification, physical cable engineering or packed texture-ready UVs. Path proximity is an input rejection filter only.'}


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def assert_inputs(args, hashes, stage):
    if (digest(args.source), digest(args.spec)) != hashes:
        raise ValueError('source or spec changed during ' + stage + '; refusing publication')


def publish_snapshot(args, report, hashes):
    # Reuse dependency remapping and safe snapshot save, but hold both results
    # privately until input hashes have also survived the actual Blender save.
    with tempfile.TemporaryDirectory(prefix='.components-', dir=args.output.parent) as directory:
        staged = SimpleNamespace(source=args.source, spec=args.spec,
                                 output=Path(directory)/args.output.name,
                                 report=Path(directory)/'staged-report.json')
        save_snapshot(staged, report)
        assert_inputs(args, hashes, 'snapshot save')
        report['lineage']['output'] = str(args.output)
        report['input_checks'].append('before_publication')
        encoded = json.dumps(report, indent=2, allow_nan=False)+'\n'
        os.link(staged.output, args.output)
        report_created = False
        try:
            with args.report.open('x', encoding='utf8') as stream:
                report_created = True
                stream.write(encoded)
            assert_inputs(args, hashes, 'publication')
        except BaseException:
            args.output.unlink()
            if report_created:
                args.report.unlink()
            raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'spec', 'output', 'report'):
        parser.add_argument('--'+name, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        check_paths(args)
        if os.path.samefile(args.source, args.spec):
            raise ValueError('source and spec must be distinct files, not hardlink aliases')
        hashes = (digest(args.source), digest(args.spec))
        with args.spec.open('rb') as stream:
            payload = stream.read(2_000_001)
        if len(payload) > 2_000_000:
            raise ValueError('spec must be at most 2000000 bytes')
        spec = validate(json.loads(payload.decode('utf8'), object_pairs_hook=unique_object))
        checks = []
        assert_inputs(args, hashes, 'validation')
        checks.append('validated')
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        lineage = {'source': str(args.source.resolve()), 'source_sha256': hashes[0],
                   'spec': str(args.spec.resolve()), 'spec_sha256': hashes[1],
                   'blender_version': bpy.app.version_string}
        bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()), use_scripts=False)
        assert_inputs(args, hashes, 'source open')
        checks.append('opened')
        result = build(spec)
        assert_inputs(args, hashes, 'construction')
        checks.append('built')
        report = {'schema_version': 1, 'command': 'build-components', 'status': 'built',
                  'lineage': lineage, 'input_checks': checks, **result}
        assert_inputs(args, hashes, 'pre-publication')
        publish_snapshot(args, report, hashes)
        return 0
    except (ValueError, KeyError, OSError, RuntimeError, ImportError) as exc:
        print(json.dumps({'status': 'error', 'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    cli = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(cli))
