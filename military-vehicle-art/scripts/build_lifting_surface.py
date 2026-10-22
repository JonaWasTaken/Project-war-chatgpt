"""Construct a new closed, chordwise-sampled aircraft lifting surface.

Offline bpy or Blender --background --disable-autoexec --python this_file --
--source existing.blend --spec filled.json --output NEW.blend --report NEW.json.
See references/lifting-surfaces.md for the deliberately bounded geometry domain.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from reconstruct_vehicle import check_paths, digest, float32, keys, number, save_snapshot, text

MAX_SPEC_BYTES = 1048576


def _ranged(value, label, low, high):
    value = number(value, label)
    if not low <= value <= high:
        raise ValueError(f'{label} must be in [{low}, {high}]')
    return value


def _cross2(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _clip_triangle(subject, clip):
    """Convex XY overlay; vertices also bound affine height differences."""
    polygon = [p[:2] for p in subject]
    for a,b in zip(clip, clip[1:]+clip[:1]):
        incoming, polygon = polygon, []
        if not incoming:
            break
        previous = incoming[-1]
        dp = _cross2(a,b,previous)
        for current in incoming:
            dc = _cross2(a,b,current)
            if (dc >= 0) != (dp >= 0):
                t = dp/(dp-dc)
                polygon.append([previous[i]+t*(current[i]-previous[i]) for i in (0,1)])
            if dc >= 0:
                polygon.append(current)
            previous, dp = current, dc
    return polygon


def _height(triangle, p):
    a,b,c = triangle
    denominator = _cross2(a,b,c)
    wa, wb = _cross2(b,c,p)/denominator, _cross2(c,a,p)/denominator
    return wa*a[2]+wb*b[2]+(1-wa-wb)*c[2]


def _check_separation(verts, faces, n, count, blunt):
    """Each skin is a graph over XY; overlay ALL triangles in each Y slab.

    A difference of affine triangle heights is affine on each convex overlay
    polygon, so its extrema occur at overlay vertices, not arbitrary samples.
    Ordered station planes prevent intersections between different slabs.
    """
    m = 2*n-2+blunt
    for k in range(count-1):
        local = verts[k*m:(k+2)*m]
        xmin, ymin, zmin = [min(p[i] for p in local) for i in range(3)]
        sx,sy,sz = [max(p[i] for p in local)-v for i,v in enumerate((xmin,ymin,zmin))]
        if min(sx,sy,sz) <= 0:
            raise ValueError('collapsed station slab')
        def triangle(face):
            points = [[(verts[i][0]-xmin)/sx, (verts[i][1]-ymin)/sy, (verts[i][2]-zmin)/sz] for i in face]
            return points if _cross2(*points) > 0 else list(reversed(points))
        offset = k*4*(n-1)
        upper = [triangle(faces[offset+4*i+j]) for i in range(n-1) for j in (0,1)]
        lower = [triangle(faces[offset+4*i+j]) for i in range(n-1) for j in (2,3)]
        leading = [(verts[j*m][0]-xmin)/sx for j in (k,k+1)]
        trailing = [(verts[j*m+n-1][0]-xmin)/sx for j in (k,k+1)]
        def bound(tri):
            return min(p[0] for p in tri), max(p[0] for p in tri)
        lower_bounds = [(tri, bound(tri)) for tri in lower]
        for top in upper:
            lo,hi = bound(top)
            for bottom,(blo,bhi) in lower_bounds:
                if hi < blo or bhi < lo:
                    continue
                polygon = _clip_triangle(top,bottom)
                if len(polygon) < 3:
                    continue
                area = abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(polygon,polygon[1:]+polygon[:1])))
                if area < 1e-15:
                    continue
                for x,y in polygon:
                    gap = _height(top,(x,y))-_height(bottom,(x,y))
                    at_edge = any(abs(x-((1-y)*e[0]+y*e[1])) <= 1e-11 for e in (leading,trailing))
                    if gap < -1e-10 or (not at_edge and gap <= 1e-10):
                        raise ValueError('upper/lower separation crosses or collapses between span stations')


def _check_placement(verts, faces, placement):
    angles = [math.radians(v) for v in placement['rotation_degrees']]
    cx,cy,cz = [math.cos(v) for v in angles]
    sx,sy,sz = [math.sin(v) for v in angles]
    origin = placement['origin']
    error = 0.0
    for x,y,z in verts:
        y,z = cx*y-sx*z, sx*y+cx*z
        x,z = cy*x+sy*z, -sy*x+cy*z
        x,y = cz*x-sz*y, sz*x+cz*y
        for a,b in zip((x,y,z),origin):
            world = a+b
            error = max(error,abs(float32(world)-world))
    for face in faces:
        a,b,c = [verts[i] for i in face]
        u,v = [[p[j]-a[j] for j in range(3)] for p in (b,c)]
        cross = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
        edge = max(math.dist(a,b),math.dist(b,c),math.dist(c,a))
        altitude = math.hypot(*cross)/edge
        if error > altitude*.001:
            raise ValueError('world placement exceeds conservative float32 resolution guard; recenter or enlarge the surface')


def _prepare(spec):
    keys(spec, ('schema_version', 'object_name', 'collection', 'airfoil', 'placement', 'stations'))
    if type(spec['schema_version']) is not int or spec['schema_version'] != 1:
        raise ValueError('schema_version must be integer 1')
    for key in ('object_name', 'collection'):
        text(spec[key], key)
    foil = spec['airfoil']
    if not isinstance(foil, dict) or foil.get('kind') not in ('naca4_vertical', 'explicit'):
        raise ValueError('airfoil kind must be naca4_vertical or explicit')
    if foil['kind'] == 'naca4_vertical':
        keys(foil, ('kind', 'samples'))
        n = foil['samples']
        if type(n) is not int or not 5 <= n <= 65:
            raise ValueError('samples must be integer 5..65')
        xs = [(1-math.cos(math.pi*i/(n-1)))/2 for i in range(n)]
    else:
        keys(foil, ('kind', 'x'), ('trailing_edge',))
        if foil.get('trailing_edge','sharp') not in ('sharp','blunt'):
            raise ValueError('explicit trailing_edge must be sharp or blunt')
        xs = foil['x']
        if not isinstance(xs, list) or not 5 <= len(xs) <= 129:
            raise ValueError('explicit x requires 5..129 corresponding samples')
        for x in xs:
            number(x, 'normalized x')
        if xs[0] != 0 or xs[-1] != 1 or any(b-a < 1e-5 for a,b in zip(xs,xs[1:])):
            raise ValueError('normalized x must increase strictly from exactly 0 to 1; minimum spacing 1e-5')
        n = len(xs)
    blunt = int(foil.get('trailing_edge') == 'blunt')
    stations = spec['stations']
    if not isinstance(stations, list) or not 2 <= len(stations) <= 64:
        raise ValueError('stations must contain 2..64 records')
    keys(spec['placement'], ('origin', 'rotation_degrees'))
    for field in ('origin', 'rotation_degrees'):
        values = spec['placement'][field]
        if not isinstance(values, list) or len(values) != 3:
            raise ValueError('placement '+field+' must contain three numbers')
        for value in values:
            limit = 100000 if field == 'origin' else 360
            _ranged(value, 'placement '+field, -limit, limit)
    verts = []
    previous_y = None
    for s in stations:
        keys(s, ('span', 'leading_edge', 'chord', 'twist_degrees', 'profile'))
        y = _ranged(s['span'], 'span', 0, 100000)
        if previous_y is not None and (y-previous_y < 1e-4 or float32(y) <= float32(previous_y)):
            raise ValueError('span stations must increase, separated by at least 1e-4 and distinct at float32 precision')
        previous_y = y
        chord = _ranged(s['chord'], 'chord', 1e-4, 10000)
        if not isinstance(s['leading_edge'], list) or len(s['leading_edge']) != 2:
            raise ValueError('leading_edge requires [x,z] offsets')
        ox, oz = [_ranged(v, 'leading_edge', -100000, 100000) for v in s['leading_edge']]
        theta = math.radians(_ranged(s['twist_degrees'], 'twist_degrees', -20, 20))
        if blunt and theta != 0:
            raise ValueError('blunt trailing-edge mode requires zero station twist')
        p = s['profile']
        if foil['kind'] == 'naca4_vertical':
            keys(p, ('thickness', 'camber', 'camber_position'))
            thickness = _ranged(p['thickness'], 'thickness', .01, .4)
            camber = _ranged(p['camber'], 'camber', -.1, .1)
            position = _ranged(p['camber_position'], 'camber_position', .1, .9)
            half = [5*thickness*(.2969*math.sqrt(x)-.126*x-.3516*x*x+.2843*x**3-.1036*x**4) for x in xs]
            half[0] = half[-1] = 0.0
            mean = [camber/position**2*(2*position*x-x*x) if x < position else
                    camber/(1-position)**2*(1-2*position+2*position*x-x*x) for x in xs]
            upper = [c+h for c,h in zip(mean,half)]
            lower = [c-h for c,h in zip(mean,half)]
        else:
            keys(p, ('upper', 'lower'))
            upper, lower = p['upper'], p['lower']
            for chain in (upper,lower):
                if not isinstance(chain, list) or len(chain) != n:
                    raise ValueError('upper/lower must correspond exactly to shared airfoil.x')
                for z in chain:
                    _ranged(z, 'normalized profile height', -.5, .5)
                if chain[0] != 0 or (not blunt and chain[-1] != 0):
                    raise ValueError('profiles must close at [0,0]; sharp profiles also close at [1,0]')
            if blunt and upper[-1]-lower[-1] < 1e-5:
                raise ValueError('blunt trailing edge requires upper-lower gap at least 1e-5 at every station')
            if any(upper[i]-lower[i] < 1e-5 for i in range(1,n-1)):
                raise ValueError('upper/lower cross, touch, or collapse in the airfoil interior')
        def point(x, z):
            return (float32(ox+chord*(x*math.cos(theta)+z*math.sin(theta))), float32(y),
                    float32(oz+chord*(-x*math.sin(theta)+z*math.cos(theta))))
        verts.extend([point(x, z) for x,z in zip(xs,upper)])
        verts.extend([point(xs[i], lower[i]) for i in range(1, n-1+blunt)])
    m = 2*n-2+blunt
    def up(k, i):
        return k*m+i
    def low(k, i):
        return up(k, i) if i == 0 or (i == n-1 and not blunt) else k*m+n+i-1
    for k in range(len(stations)):
        for index in (up,low):
            if any(verts[index(k,i+1)][0] <= verts[index(k,i)][0] for i in range(n-1)):
                raise ValueError('twist overturns the projected airfoil graph or float32 collapses an edge; reduce twist or samples, or recenter')
    faces = []
    for k in range(len(stations)-1):
        for i in range(n-1):
            for index, reverse in ((up, False), (low, True)):
                a, b, c, d = index(k,i), index(k,i+1), index(k+1,i+1), index(k+1,i)
                for face in ((a,b,c), (a,c,d)):
                    faces.append(tuple(reversed(face)) if reverse else face)
    if blunt:
        for k in range(len(stations)-1):
            a,b,c,d = up(k,n-1),low(k,n-1),low(k+1,n-1),up(k+1,n-1)
            faces.extend(((a,b,c),(a,c,d)))
    for k, reverse in ((0, False), (len(stations)-1, True)):
        for i in range(n-1):
            quad = [up(k,i), low(k,i), low(k,i+1), up(k,i+1)]
            poly = list(dict.fromkeys(quad))
            for j in range(1,len(poly)-1):
                face = (poly[0], poly[j], poly[j+1])
                faces.append(tuple(reversed(face)) if reverse else face)
    for face in faces:
        a,b,c = [verts[i] for i in face]
        u,v = [[p[j]-a[j] for j in range(3)] for p in (b,c)]
        cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        if math.hypot(*cross) <= 1e-12*max(sum(q*q for q in u),sum(q*q for q in v)):
            raise ValueError('float32 collapsed or ill-conditioned mesh triangle')
    _check_separation(verts, faces, n, len(stations), blunt)
    _check_placement(verts, faces, spec['placement'])
    return verts, faces


def validate(spec):
    verts, faces = _prepare(spec)
    return {'status': 'valid', 'vertices': len(verts), 'triangles': len(faces)}


def _add_uv(mesh, spec):
    foil = spec['airfoil']
    n = foil['samples'] if foil['kind'] == 'naca4_vertical' else len(foil['x'])
    xs = [(1-math.cos(math.pi*i/(n-1)))/2 for i in range(n)] if foil['kind'] == 'naca4_vertical' else foil['x']
    blunt = int(foil.get('trailing_edge') == 'blunt')
    count, m = len(spec['stations']), 2*n-2+blunt
    side_count = 4*(n-1)*(count-1)
    trailing_count = 2*blunt*(count-1)
    cap_start = side_count+trailing_count
    cap_count = 2*(n-2)+blunt
    layer = mesh.uv_layers.new(name='LiftingSurfaceUV')
    groups = {}
    cap_bounds = {}
    for station in (0,count-1):
        coords = [v.co for v in mesh.vertices[station*m:(station+1)*m]]
        cap_bounds[station] = [(min(p[i] for p in coords), max(p[i] for p in coords)) for i in (0,2)]
    start,end = spec['stations'][0]['span'],spec['stations'][-1]['span']
    for face in mesh.polygons:
        group = ('upper' if face.index % 4 < 2 else 'lower') if face.index < side_count else ('trailing_edge' if face.index < cap_start else ('root' if face.index < cap_start+cap_count else 'tip'))
        face.use_smooth = group in ('upper','lower')
        for loop_index in face.loop_indices:
            vi = mesh.loops[loop_index].vertex_index
            station, i = divmod(vi,m)
            if i >= n:
                i = i-n+1
            if group in ('upper','lower'):
                u = (.02 if group == 'upper' else .52)+.46*xs[i]
                v = .24+.74*(spec['stations'][station]['span']-start)/(end-start)
            elif group == 'trailing_edge':
                u = .02+.96*(spec['stations'][station]['span']-start)/(end-start)
                v = .23 if vi % m == n-1 else .205
            else:
                (xmin,xmax),(zmin,zmax) = cap_bounds[station]
                co = mesh.vertices[vi].co
                u = (.02 if group == 'root' else .52)+.46*(co.x-xmin)/(xmax-xmin)
                v = .02+.18*(co.z-zmin)/(zmax-zmin)
            layer.data[loop_index].uv = (u,v)
            groups.setdefault(mesh.loops[loop_index].edge_index,set()).add(group)
    for edge_index, uses in groups.items():
        mesh.edges[edge_index].use_seam = len(uses) > 1
        mesh.edges[edge_index].use_edge_sharp = len(uses) > 1
    for face in mesh.polygons:
        a,b,c = [layer.data[i].uv for i in face.loop_indices]
        if abs((b.x-a.x)*(c.y-a.y)-(b.y-a.y)*(c.x-a.x)) <= 1e-15:
            raise ValueError('float32 UV triangle collapsed; reduce span/chord sample aspect ratio')
    return {'name': layer.name, 'islands': ['upper','lower','root','tip']+(['trailing_edge'] if blunt else []),
            'method': 'separate_skin_parameter_grids_and_planar_caps', 'texel_density_verified': False}


def build(spec):
    import bpy
    import bmesh
    if bpy.context.mode != 'OBJECT' or any(mesh.is_editmode for mesh in bpy.data.meshes):
        raise ValueError('Object-mode source is required')
    verts, faces = _prepare(spec)
    name = spec['object_name']
    if name in bpy.data.objects or name in bpy.data.meshes:
        raise ValueError('object/mesh name is already owned: '+name)
    if spec['collection'] in bpy.data.collections:
        raise ValueError('collection name is already owned')
    mesh = bpy.data.meshes.new(name)
    obj = collection = None
    try:
        mesh.from_pydata(verts, [], faces)
        mesh.update()
        uv = _add_uv(mesh,spec)
        # Relative conditioning does not catch Blender's absolute-scale normal
        # fallback. Compare native normals with double arithmetic on stored co.
        for face in mesh.polygons:
            a,b,c = [tuple(mesh.vertices[i].co) for i in face.vertices]
            u,v = [[p[j]-a[j] for j in range(3)] for p in (b,c)]
            cross = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
            length = math.hypot(*cross)
            dot = sum(n*q/length for n,q in zip(face.normal,cross))
            if not math.isfinite(dot) or dot < .99999:
                raise ValueError('Blender native face normal disagrees with triangle geometry; enlarge the surface or simplify its samples')
        bm = bmesh.new()
        try:
            bm.from_mesh(mesh)
            volume = bm.calc_volume(signed=True)
            if not math.isfinite(volume) or volume <= 0 or any(not edge.is_manifold or not edge.is_contiguous for edge in bm.edges):
                raise ValueError('constructed mesh is not a positive-volume oriented manifold')
        finally:
            bm.free()
        obj = bpy.data.objects.new(name, mesh)
        obj.location = spec['placement']['origin']
        obj.rotation_mode = 'XYZ'
        obj.rotation_euler = [math.radians(v) for v in spec['placement']['rotation_degrees']]
        obj['construction_tool'] = 'build_lifting_surface.v1'
        obj['construction_spec_json'] = json.dumps(spec,allow_nan=False,sort_keys=True)
        collection = bpy.data.collections.new(spec['collection'])
        bpy.context.scene.collection.children.link(collection)
        collection.objects.link(obj)
    except BaseException:
        if obj is not None:
            bpy.data.objects.remove(obj,do_unlink=True)
        if collection is not None:
            bpy.data.collections.remove(collection)
        bpy.data.meshes.remove(mesh)
        raise
    segments = [{'sweep_degrees': math.degrees(math.atan2(b['leading_edge'][0]-a['leading_edge'][0], b['span']-a['span'])),
                 'dihedral_degrees': math.degrees(math.atan2(b['leading_edge'][1]-a['leading_edge'][1], b['span']-a['span']))}
                for a,b in zip(spec['stations'], spec['stations'][1:])]
    return {'status': 'built', 'object': name, 'collection': collection.name, 'segments': segments, 'uv': uv,
            'units': {'lengths':'source_blender_units', 'scene_system':bpy.context.scene.unit_settings.system,
                      'scene_scale_length':bpy.context.scene.unit_settings.scale_length},
            'mesh': {'vertices': len(verts), 'triangles': len(faces),
                     'volume_blender_units_cubed': volume, 'closed_caps': ['root','tip'],
                     'bounds_local': [[min(v[i] for v in verts) for i in range(3)],
                                      [max(v[i] for v in verts) for i in range(3)]],
                     'oriented_manifold': True, 'skin_separation_method':'full_triangle_overlay_in_each_span_slab'},
            'limitations': ['Construction geometry, not aerodynamic accuracy or aircraft/reference identity.',
                            'No wing/body blends, collision with other scene objects, control-surface gaps, or pointed zero-chord tips.',
                            'Triangulated piecewise-linear skins and planar caps; no automatic retopology, baking or engineering certification.']}


def _unique_object(pairs):
    result = {}
    for key,value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key: '+key)
        result[key] = value
    return result


def _dependencies():
    import bpy
    paths = sorted({str(Path(p).resolve()) for p in bpy.utils.blend_paths(absolute=True,packed=False)})
    if len(paths) > 256:
        raise ValueError('at most 256 external dependency files are supported')
    rows,total = [],0
    for name in paths:
        path = Path(name)
        if not path.is_file():
            raise ValueError('external dependency is missing or not a supported static file: '+name)
        size = path.stat().st_size
        total += size
        if size > 536870912 or total > 2147483648:
            raise ValueError('external dependencies exceed 512 MiB per file / 2 GiB total hashing limit')
        rows.append({'path':name,'sha256':digest(path),'bytes':size})
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source','spec','output','report'):
        parser.add_argument('--'+name,required=True,type=Path)
    args = parser.parse_args(argv)
    try:
        check_paths(args)
        if os.path.samefile(args.source,args.spec):
            raise ValueError('source and spec must not be hardlink aliases')
        if args.spec.stat().st_size > MAX_SPEC_BYTES:
            raise ValueError('spec exceeds 1 MiB size limit')
        source_hash,spec_hash = digest(args.source),digest(args.spec)
        spec = json.loads(args.spec.read_text(encoding='utf8'),object_pairs_hook=_unique_object)
        validate(spec)
        if digest(args.spec) != spec_hash:
            raise ValueError('spec changed during validation; refusing to open source')
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute = False
        bpy.ops.wm.open_mainfile(filepath=str(args.source.resolve()),use_scripts=False)
        dependencies = _dependencies()
        lineage = {'source':str(args.source.resolve()),'source_sha256':source_hash,
                   'spec':str(args.spec.resolve()),'spec_sha256':spec_hash,'blender_version':bpy.app.version_string}
        report = {'schema_version':1,'command':'build-lifting-surface','lineage':lineage,**build(spec)}
        if digest(args.source) != source_hash or digest(args.spec) != spec_hash:
            raise ValueError('source or spec changed during operation; refusing publication')
        if _dependencies() != dependencies:
            raise ValueError('external dependencies changed during operation; refusing publication')
        report['dependencies'] = {'unchanged':True,'files':dependencies,
                                  'scope':'existing unpacked static files exposed by bpy.utils.blend_paths; not copied or locked'}
        save_snapshot(args,report)
        return 0
    except (ValueError,KeyError,OSError,RuntimeError,ImportError) as exc:
        print(json.dumps({'status':'error','error':str(exc)}),file=sys.stderr)
        return 2


if __name__ == '__main__':
    cli = sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]
    raise SystemExit(main(cli))
