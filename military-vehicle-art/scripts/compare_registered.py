"""Connect registered-camera render manifests to real reference diagnostics."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile

import reference_match


def require(condition, message):
    if not condition:
        raise ValueError(message)


def confined(root, path, exists=True):
    path = Path(path)
    path = path if path.is_absolute() else root/path
    require('..' not in path.parts, 'Traversal is not supported.')
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise ValueError('All source, manifest, reference and output files must be inside the job.') from exc
    require(parts, 'A job-relative file/directory is required.')
    cursor = root
    for part in parts:
        cursor /= part
        require(not cursor.is_symlink(), 'Symlink inputs/outputs are not supported.')
    if exists:
        require(cursor.is_file(), 'Missing regular input: '+str(cursor))
    return cursor


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compare(manifest_path, reference_path, root, output):
    root = Path(root).resolve(strict=True)
    require(root.is_dir(), 'root must be a directory.')
    manifest_path, reference_path = [confined(root,p) for p in (manifest_path,reference_path)]
    output = confined(root,output,exists=False)
    if os.path.lexists(output):
        raise FileExistsError('Choose a new comparison directory.')
    require(output.parent.is_dir(), 'Output parent directory must exist.')
    manifest_bytes, reference_bytes = manifest_path.read_bytes(), reference_path.read_bytes()
    manifest, spec = json.loads(manifest_bytes), json.loads(reference_bytes)
    require(isinstance(manifest,dict) and type(manifest.get('schema_version')) is int and
            manifest['schema_version'] == 1 and manifest.get('kind') == 'registered_camera_render',
            'Expected a schema-1 registered_camera_render manifest, not a studio inspection rig.')
    require(isinstance(spec,dict) and set(spec) == {'schema_version','reference','registration','features'},
            'Reference spec must contain schema_version, reference, registration and features only; model is derived from the renderer.')
    reference = spec.get('reference')
    require(isinstance(reference,dict), 'Reference photo/mask metadata required.')
    for field in ('path','mask_path'):
        require(isinstance(reference.get(field),str), 'Reference photo/mask paths must be strings.')
        confined(root,reference[field])
    camera = manifest.get('camera')
    require(isinstance(camera,dict) and camera.get('type') in ('PERSP','ORTHO') and
            isinstance(camera.get('name'),str) and camera['name'].strip(), 'Supported named camera metadata required.')
    matrix = camera.get('matrix_world')
    require(isinstance(matrix,list) and len(matrix)==4 and all(isinstance(row,list) and len(row)==4 for row in matrix),
            'Camera matrix must be 4x4.')
    for row in matrix:
        for value in row:
            require(type(value) in (int,float) and math.isfinite(value), 'Camera matrix entries must be finite numbers, not booleans.')
    require(matrix[3] == [0,0,0,1], 'Camera world matrix must be affine.')
    size = manifest.get('image_size')
    require(isinstance(size,list) and len(size)==2 and all(type(v) is int and v>0 for v in size),
            'Render image_size needs two positive integers.')
    require(isinstance(manifest.get('registration_note'),str) and manifest['registration_note'].strip(),
            'Renderer registration note required; it does not independently prove calibration.')
    source = manifest.get('source')
    artifacts = manifest.get('artifacts')
    require(isinstance(source,dict) and isinstance(artifacts,dict), 'Source and rendered artifacts required.')
    source_path = confined(root,source.get('path',''))
    source_relative = source_path.relative_to(root).as_posix()
    reference_match.checked_file(root,source_relative,source.get('sha256'))
    model = {'source_path':source_relative,'source_sha256':source['sha256'],'foreground':'light'}
    for role, key, digest_key in (('mask','path','sha256'),('detail','detail_path','detail_sha256')):
        item = artifacts.get(role)
        require(isinstance(item,dict) and isinstance(item.get('path'),str), 'Manifest needs mask and detail artifacts.')
        raw = item['path']
        require(raw and not Path(raw).is_absolute() and '\\' not in raw and ':' not in raw and
                all(p not in ('','.','..') for p in raw.split('/')), 'Artifact paths must stay relative to the render directory.')
        path = confined(root,manifest_path.parent/raw)
        path.relative_to(manifest_path.parent)
        relative = path.relative_to(root).as_posix()
        _, data = reference_match.checked_file(root,relative,item.get('sha256'))
        image = reference_match.image_from_bytes(data,mask=role=='mask')
        require(list(image.size)==size, 'Manifest image_size does not match decoded render dimensions.')
        model[key], model[digest_key] = relative,item['sha256']
    registration = spec.get('registration')
    require(isinstance(registration,dict), 'Reference registration declaration required.')
    registration = {**registration,'render_manifest':{'path':manifest_path.relative_to(root).as_posix(),'sha256':sha(manifest_bytes)},
                    'render_camera':camera,'renderer_registration_note':manifest['registration_note']}
    paired = {**spec,'model':model,'registration':registration}
    created = False
    with tempfile.TemporaryDirectory(prefix='.pair-',dir=output.parent) as temporary:
        stage = Path(temporary)/'comparison'
        report = reference_match.evaluate(paired,root,stage)
        (stage/'paired-spec.json').write_text(json.dumps(paired,indent=2,allow_nan=False)+'\n')
        require(manifest_path.read_bytes()==manifest_bytes and reference_path.read_bytes()==reference_bytes,
                'Input manifest/spec changed during comparison.')
        for item in report['inputs'].values():
            confined(root,item['path'])
            reference_match.checked_file(root,item['path'],item['sha256'])
        try:
            output.mkdir()  # Exclusive ownership; never replace an existing directory.
            created = True
            for path in sorted(stage.iterdir(),key=lambda p:(p.name=='report.json',p.name)):
                os.link(path,output/path.name)
        except BaseException:
            if created:
                shutil.rmtree(output)
            raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','reference-spec','root','output'):
        parser.add_argument('--'+name,required=True,type=Path)
    args = parser.parse_args(argv)
    try:
        report = compare(args.manifest,args.reference_spec,args.root,args.output)
    except (OSError,ValueError,TypeError,KeyError,RuntimeError,OverflowError,ImportError) as exc:
        print(json.dumps({'status':'error','error':str(exc)}))
        return 2
    print(json.dumps({'status':report['diagnostic_status'],'metrics':report['metrics'],'output':str(args.output)},indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
