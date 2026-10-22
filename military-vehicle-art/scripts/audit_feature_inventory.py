#!/usr/bin/env python3
"""Read-only trace from explicit reference features to actual evaluated mesh anchors.

This is NOT photo feature recognition, exhaustive inventory or an accuracy score.
See references/feature-inventory.md. Run in a disposable official bpy process.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from probe_geometry import fields, require, text, number, vector, digest, exact_object, finite_matrix

LIMITATIONS=[
    'Feature inventory is supplied by the author; unseen or omitted details cannot be detected automatically.',
    'Images, crops, observations and position bases are declared evidence, not authenticated observations.',
    'Geometry presence and an anchor position do not verify feature shape, count, size, orientation, material or photographic likeness.',
    'All positions/tolerances are Blender world units, not inferred SI metres or recovered from photo pixels.',
    'Viewport evaluated mesh only; no render displacement, instances or Geometry Nodes. External Blender dependencies are not fingerprinted.',
    'Counts apply only to this declared inventory; no whole-object fidelity percentage or automatic approval is produced.'
]

def unique(pairs):
    result={}
    for key,value in pairs:
        require(key not in result,'duplicate JSON key: '+key)
        result[key]=value
    return result


def validate(spec):
    fields(spec,{'schema_version','scene','view_layer','evaluation_frame','subject','scope_note','evidence','regions','features'})
    require(type(spec['schema_version']) is int and spec['schema_version']==1,'schema_version must be integer 1')
    for key in ('scene','view_layer','subject','scope_note'):text(spec[key],key)
    require(type(spec['evaluation_frame']) is int and -1000000<=spec['evaluation_frame']<=1000000,'invalid evaluation_frame')
    for key,limit in (('evidence',64),('regions',256),('features',4096)):
        require(isinstance(spec[key],list) and 1<=len(spec[key])<=limit,key+' must be a nonempty bounded list')
    evidence_ids=set()
    for row in spec['evidence']:
        fields(row,{'id','path','sha256'});text(row['id'],'evidence ID')
        require(row['id'] not in evidence_ids,'duplicate evidence ID');evidence_ids.add(row['id'])
    region_ids=set()
    for row in spec['regions']:
        fields(row,{'id','coverage_note'});text(row['id'],'region ID');text(row['coverage_note'],'coverage_note')
        require(row['id'] not in region_ids,'duplicate region ID');region_ids.add(row['id'])
    feature_ids=set();anchors=set()
    for row in spec['features']:
        fields(row,{'id','region','description','epistemic','uncertainty','observations','model'})
        for key in ('id','region','description','uncertainty'):text(row[key],key)
        require(row['id'] not in feature_ids,'duplicate feature ID');feature_ids.add(row['id'])
        require(row['region'] in region_ids,'feature references unknown region')
        require(row['epistemic'] in ('observed','authored','inferred','unknown'),'invalid epistemic state')
        require(isinstance(row['observations'],list) and len(row['observations'])<=64,'invalid observation list')
        require(row['epistemic'] not in ('observed','authored') or len(row['observations'])>0,'observed/authored features require an evidence crop')
        for observation in row['observations']:
            fields(observation,{'evidence','region_px'})
            require(isinstance(observation['evidence'],str) and observation['evidence'] in evidence_ids,'observation references unknown evidence')
            crop=observation['region_px']
            require(isinstance(crop,list) and len(crop)==4 and all(type(v) is int for v in crop),'region_px requires four integers')
            require(0<=crop[0]<crop[2]<=32768 and 0<=crop[1]<crop[3]<=32768,'invalid evidence crop bounds')
        model=row['model']
        if model is not None:
            fields(model,{'object','anchor','vertex_index','target_world','tolerance','position_basis'})
            text(model['object'],'model object')
            require(model['anchor'] in ('bounds_center','evaluated_vertex'),'unsupported anchor')
            if model['anchor']=='bounds_center':require(model['vertex_index'] is None,'bounds_center vertex_index must be null')
            else:require(type(model['vertex_index']) is int and 0<=model['vertex_index']<2000000,'invalid evaluated vertex index')
            if model['target_world'] is None:
                require(model['tolerance'] is None and model['position_basis'] is None,'unchecked positions require null tolerance/basis')
            else:
                target=vector(model['target_world'],'target_world')
                require(all(abs(v)<=1e8 for v in target),'target_world exceeds supported numeric range')
                tolerance=number(model['tolerance'],'tolerance',positive=True)
                require(1e-12<=tolerance<=1e6,'tolerance outside 1e-12..1e6 world units')
                text(model['position_basis'],'position_basis')
            anchor=(model['object'],model['anchor'],model['vertex_index'])
            require(anchor not in anchors,'multiple feature IDs reuse the same geometry anchor');anchors.add(anchor)
    return spec


def evidence_records(spec,root):
    from PIL import Image
    result={};total=0
    for row in spec['evidence']:
        fields(row,{'id','path','sha256'})
        text(row['id'],'evidence.id');text(row['path'],'evidence.path')
        require(row['id'] not in result,'duplicate evidence ID')
        require(isinstance(row['sha256'],str) and re.fullmatch('[0-9a-f]{64}',row['sha256']) is not None,'invalid evidence sha256')
        supplied=Path(row['path'])
        require(not supplied.is_absolute(),'evidence path must be relative to the spec directory')
        path=(root/supplied).resolve()
        require(path.is_relative_to(root.resolve()),'evidence path escapes the spec directory')
        current=root
        for part in supplied.parts:
            current=current/part
            require(not current.is_symlink(),'symlink evidence paths are unsupported')
        require(path.is_file() and digest(path)==row['sha256'],'missing/stale evidence image')
        total+=path.stat().st_size
        require(total<=134217728,'evidence byte budget exceeded')
        with Image.open(path) as image:
            require(image.format in ('PNG','JPEG') and getattr(image,'n_frames',1)==1,'only static PNG/JPEG references supported')
            require(1<=image.width*image.height<=4194304,'evidence image exceeds supported pixel budget')
            size=list(image.size);image.verify()
        # JPEG verify() checks headers only. Decode within the pixel budget too.
        with Image.open(path) as image:
            image.load()
        result[row['id']]={**row,'resolved_path':str(path),'size':size}
    for feature in spec['features']:
        for observation in feature['observations']:
            size=result[observation['evidence']]['size'];crop=observation['region_px']
            require(crop[2]<=size[0] and crop[3]<=size[1],'evidence crop outside actual image')
    return result


def audit(spec,evidence):
    import bpy
    validate(spec)
    scene=bpy.data.scenes.get(spec['scene']);require(scene is not None,'missing scene')
    layer=scene.view_layers.get(spec['view_layer']);require(layer is not None,'missing view layer')
    scene.frame_set(spec['evaluation_frame'])
    result=[];cache={};total_vertices=0
    render_visible=set()
    def visit(layer_collection,hidden=False):
        collection=layer_collection.collection
        hidden=hidden or layer_collection.exclude or collection.hide_render
        if not hidden:render_visible.update(obj.name for obj in collection.objects if not obj.hide_render)
        for child in layer_collection.children:visit(child,hidden)
    visit(layer.layer_collection)
    with bpy.context.temp_override(scene=scene,view_layer=layer):
        graph=bpy.context.evaluated_depsgraph_get()
        for row in spec['features']:
            measured=None;distance=None;model=row['model']
            if model is None:
                state='unresolved' if row['epistemic']=='unknown' else 'not_modelled'
            elif model['object'] not in bpy.data.objects:
                state='missing_geometry'
            else:
                name=model['object']
                if name not in cache:
                    obj=exact_object(name,scene,layer)
                    require(obj.type=='MESH','feature object must be a mesh')
                    require(obj.name in render_visible,'render-hidden feature is unsupported')
                    evaluated=obj.evaluated_get(graph);finite_matrix(evaluated.matrix_world)
                    mesh=evaluated.to_mesh()
                    try:
                        total_vertices+=len(mesh.vertices)
                        require(total_vertices<=2000000,'evaluated vertex workload exceeds 2000000')
                        require(len(mesh.vertices)>0 and len(mesh.polygons)>0,'empty feature mesh')
                        require(any(math.isfinite(p.area) and p.area>1e-20 for p in mesh.polygons),'degenerate feature mesh has no usable area')
                        coords=[tuple(evaluated.matrix_world@v.co) for v in mesh.vertices]
                        require(all(math.isfinite(x) for p in coords for x in p),'nonfinite evaluated geometry')
                        mesh.calc_loop_triangles()
                        require(len(mesh.loop_triangles)<=4000000,'evaluated triangle workload exceeds 4000000')
                        usable=False
                        for triangle in mesh.loop_triangles:
                            a,b,c=[coords[index] for index in triangle.vertices]
                            u=[b[i]-a[i] for i in range(3)];v=[c[i]-a[i] for i in range(3)]
                            area=math.hypot(u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0])/2
                            if math.isfinite(area) and area>1e-20:
                                usable=True;break
                        require(usable,'world-transformed feature mesh has no usable area')
                        cache[name]=coords
                    finally:evaluated.to_mesh_clear()
                coords=cache[name]
                if model['anchor']=='bounds_center':
                    measured=[(min(p[i] for p in coords)+max(p[i] for p in coords))/2 for i in range(3)]
                else:
                    require(model['vertex_index']<len(coords),'evaluated vertex index outside mesh')
                    measured=list(coords[model['vertex_index']])
                if model['target_world'] is None:state='geometry_present_position_unchecked'
                else:
                    distance=math.dist(measured,model['target_world'])
                    state='position_within_tolerance' if distance<=model['tolerance'] else 'position_outside_tolerance'
            result.append({**row,'state':state,'measured_world':measured,'position_error_world_units':distance})
    counts={key:sum(row['epistemic']==key for row in result) for key in ('observed','authored','inferred','unknown')}
    counts['declared_features']=len(result)
    states={key:sum(row['state']==key for row in result) for key in sorted(set(r['state'] for r in result))}
    return {'features':result,'summary':counts,'geometry_states':states,
            'regions':[{**region,'declared_features':sum(row['region']==region['id'] for row in result)} for region in spec['regions']],
            'subject':spec['subject'],'scope_note':spec['scope_note'],'scene':spec['scene'],
            'view_layer':spec['view_layer'],'evaluation_frame':spec['evaluation_frame'],'limitations':LIMITATIONS}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','spec','report'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        source,specpath,reportpath=[p.absolute() for p in (args.source,args.spec,args.report)]
        require(source.suffix.lower()=='.blend' and source.is_file() and specpath.is_file(),'existing .blend source and spec required')
        require(not os.path.lexists(reportpath) and reportpath.parent.is_dir(),'report must be a new path in an existing directory')
        require(specpath.stat().st_size<=1048576,'spec exceeds 1 MiB')
        hashes={str(p.resolve()):digest(p) for p in (source,specpath)}
        tools={name:digest(Path(__file__).resolve().with_name(name)) for name in ('audit_feature_inventory.py','probe_geometry.py')}
        spec=validate(json.loads(specpath.read_text(encoding='utf8'),object_pairs_hook=unique))
        evidence=evidence_records(spec,specpath.parent)
        for row in evidence.values():hashes[row['resolved_path']]=row['sha256']
        import bpy
        bpy.context.preferences.filepaths.use_scripts_auto_execute=False
        bpy.ops.wm.open_mainfile(filepath=str(source.resolve()),use_scripts=False)
        report={'schema_version':1,'command':'audit-feature-inventory','status':'computed_not_acceptance',
                'lineage':{'source':str(source.resolve()),'source_sha256':hashes[str(source.resolve())],
                           'spec':str(specpath.resolve()),'spec_sha256':hashes[str(specpath.resolve())],
                           'blender_version':bpy.app.version_string},
                'evidence':list(evidence.values()),'tool_sha256':tools,**audit(spec,evidence)}
        for path,value in hashes.items():require(digest(path)==value,'input changed during audit: '+path)
        for name,value in tools.items():require(digest(Path(__file__).resolve().with_name(name))==value,'tool changed during audit')
        with tempfile.TemporaryDirectory(prefix='.inventory-',dir=reportpath.parent) as stage:
            staged=Path(stage)/'report.json';staged.write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
            os.link(staged,reportpath)
        return 0
    except (ValueError,KeyError,TypeError,OSError,RuntimeError,ImportError,OverflowError) as exc:
        print('feature-inventory: '+str(exc),file=sys.stderr);return 2

if __name__=='__main__':
    raise SystemExit(main(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else None))
