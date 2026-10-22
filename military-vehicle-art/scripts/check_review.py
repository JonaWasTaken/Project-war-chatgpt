#!/usr/bin/env python3
"""Read-only review-record checks; never an artistic-quality evaluator."""
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath

LIMITATION = ('Record integrity only: this tool does not inspect image content, '
              'judge artistic quality, or authenticate user approval.')
CATEGORIES = ('silhouette', 'proportions', 'fit', 'shading', 'materials',
              'readability', 'motion', 'regression')


def text(value):
    return isinstance(value, str) and bool(value.strip())


def choice(value, options):
    return isinstance(value, str) and value in options


def verify_fingerprint(item, root, label, errors):
    if not isinstance(item, dict):
        errors.append(f'{label} must be an object.')
        return False
    raw, expected = item.get('path'), item.get('sha256')
    if not text(raw) or Path(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
        errors.append(f'{label}.path must be job-relative.')
        return False
    if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
        errors.append(f'{label}.sha256 must be an actual lowercase SHA-256 digest.')
        return False
    try:
        path = (root / raw).resolve(strict=True)
        path.relative_to(root)
        if not path.is_file() or path.stat().st_size == 0:
            raise ValueError('not a nonempty regular file')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected:
            errors.append(f'{label} bytes differ from the reviewed fingerprint.')
            return False
    except (OSError, ValueError, RuntimeError):
        errors.append(f'{label} file is missing, empty, unreadable, or escapes the job directory.')
        return False
    return True


def validate(record, root):
    errors = []
    if not isinstance(record, dict):
        return ['Review must be a JSON object.']
    if type(record.get('schema_version')) is not int or record['schema_version'] != 2:
        errors.append('schema_version must be 2; migrate old reviews without fabricating new evidence.')
    gate = record.get('gate')
    if not choice(gate, ('concept', 'blockout', 'assemblies', 'materials', 'delivery')):
        errors.append('Unknown gate.')
    version = record.get('model_version')
    if not text(version):
        errors.append('model_version must be nonempty.')

    source = record.get('source')
    verify_fingerprint(source, root, 'source', errors)
    if not isinstance(source, dict) or source.get('version') != version:
        errors.append('source.version must match the reviewed model_version.')

    evidence = record.get('evidence')
    if not isinstance(evidence, list):
        errors.append('evidence must be a list.')
        evidence = []
    known = {}
    inspected_renders = set()
    for index, item in enumerate(evidence):
        label = f'evidence[{index}]'
        if not isinstance(item, dict):
            errors.append(f'{label} must be an object.')
            continue
        raw = item.get('path')
        valid_path = False
        if not text(raw):
            errors.append(f'{label}.path must be nonempty.')
        elif Path(raw).is_absolute() or PureWindowsPath(raw).is_absolute():
            errors.append(f'{label}.path must be job-relative.')
        else:
            try:
                candidate = (root / raw).resolve(strict=True)
                candidate.relative_to(root)
                valid_path = candidate.is_file() and candidate.stat().st_size > 0
                if not valid_path:
                    errors.append(f'{label}.path must be a nonempty regular file.')
            except (OSError, ValueError, RuntimeError):
                errors.append(f'{label}.path is missing or escapes the job directory.')
        if text(raw):
            if raw in known:
                errors.append(f'{label}.path is duplicated.')
            known[raw] = item
        if item.get('version') != version or not text(item.get('version')):
            errors.append(f'{label} has stale or missing version.')
        if not text(item.get('finding')):
            errors.append(f'{label}.finding must describe the actual check.')
        valid_fingerprint = verify_fingerprint(item, root, label, errors)
        kind = item.get('kind')
        if not choice(kind, ('render', 'artifact')):
            errors.append(f'{label}.kind must be render or artifact.')
        if kind == 'render':
            if item.get('inspected') is not True:
                errors.append(f'{label} render was not recorded as inspected.')
            if not text(item.get('view')):
                errors.append(f'{label}.view must identify the inspected view.')
            if (valid_path and valid_fingerprint and item.get('inspected') is True and
                    text(item.get('view')) and item.get('version') == version and
                    text(item.get('finding'))):
                inspected_renders.add(raw)
    if not inspected_renders:
        errors.append('At least one current, inspected render record is required.')
    required_views = record.get('required_views')
    if not isinstance(required_views, list) or not required_views or any(not text(v) for v in required_views):
        errors.append('required_views must list the agreed inspection views.')
    else:
        observed_views = {known[p]['view'] for p in inspected_renders}
        for view in required_views:
            if view not in observed_views:
                errors.append(f'Required inspected view is missing: {view}.')
    if type(record.get('motion_required')) is not bool:
        errors.append('motion_required must be an explicit boolean from the brief.')

    coverage = record.get('coverage')
    if not isinstance(coverage, dict):
        errors.append('coverage must be an object.')
        coverage = {}
    for category in CATEGORIES:
        check = coverage.get(category)
        if not isinstance(check, dict):
            errors.append(f'coverage.{category} is missing or invalid.')
            continue
        status = check.get('status')
        required = {'silhouette', 'readability'}
        if gate != 'concept':
            required.update(('proportions', 'fit', 'regression'))
        if gate in ('assemblies', 'materials', 'delivery'):
            required.add('shading')
        if gate in ('materials', 'delivery'):
            required.add('materials')
        if gate == 'delivery' and record.get('motion_required') is True:
            required.add('motion')
        if category in required and status == 'na':
            errors.append(f'coverage.{category} cannot be not applicable at this gate.')
        if not choice(status, ('pass', 'fail', 'na', 'blocked')):
            errors.append(f'coverage.{category} has an unknown status.')
        if status in ('fail', 'blocked'):
            errors.append(f'coverage.{category} is not ready: {status}.')
        if not text(check.get('reason')):
            errors.append(f'coverage.{category}.reason is required.')
        if status in ('pass', 'fail'):
            paths = check.get('evidence_paths')
            if (not isinstance(paths, list) or not paths or
                    any(not text(p) or p not in inspected_renders for p in paths)):
                errors.append(f'coverage.{category} must cite current inspected render evidence.')

    defects = record.get('defects')
    if not isinstance(defects, list):
        errors.append('defects must be a list.')
        defects = []
    ids = set()
    for index, defect in enumerate(defects):
        label = f'defects[{index}]'
        if not isinstance(defect, dict):
            errors.append(f'{label} must be an object.')
            continue
        identifier = defect.get('id')
        if not text(identifier) or identifier in ids:
            errors.append(f'{label}.id must be nonempty and unique.')
        else:
            ids.add(identifier)
        if not text(defect.get('description')):
            errors.append(f'{label}.description is required.')
        severity, state = defect.get('severity'), defect.get('state')
        if not choice(severity, ('blocker', 'important', 'minor')):
            errors.append(f'{label} has unknown severity.')
        if not choice(state, ('open', 'fixed', 'accepted')):
            errors.append(f'{label} has unknown state.')
        if severity == 'blocker' and state != 'fixed':
            errors.append(f'{label} blocker must be fixed, not accepted or left open.')
        if severity == 'important' and state == 'open':
            errors.append(f'{label} important defect remains open.')
        if state == 'fixed':
            path = defect.get('recheck_evidence')
            if not text(path) or path not in inspected_renders:
                errors.append(f'{label} fixed defect requires current inspected recheck_evidence.')
        if state == 'accepted' and not text(defect.get('acceptance_reference')):
            errors.append(f'{label} accepted defect requires actual user acceptance_reference.')

    approval = record.get('approval')
    if not isinstance(approval, dict):
        errors.append('approval must be an object.')
    else:
        status = approval.get('status')
        allowed = ('approved', 'delegated') if gate in ('concept', 'blockout') else ('approved', 'delegated', 'not_required')
        if not choice(status, allowed):
            errors.append('approval is not ready for this gate.')
        if status in ('approved', 'delegated'):
            if approval.get('model_version') != version or not text(approval.get('model_version')):
                errors.append('approval.model_version is stale or missing.')
            if approval.get('gate') != gate:
                errors.append('approval.gate does not match this gate.')
            for key in ('reference', 'scope'):
                if not text(approval.get(key)):
                    errors.append(f'approval.{key} must identify actual authorization.')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('review', type=Path)
    parser.add_argument('--root', type=Path, required=True, help='Job directory for evidence files')
    args = parser.parse_args()
    try:
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError('--root must be an existing directory')
        record = json.loads(args.review.read_text(encoding='utf-8'))
        errors = validate(record, root)
    except (OSError, ValueError, RecursionError) as exc:
        print(json.dumps({'status': 'input-error', 'errors': [str(exc)], 'limitation': LIMITATION}))
        return 2
    print(json.dumps({'status': 'issues-found' if errors else 'record-ready',
                      'errors': errors, 'limitation': LIMITATION}, indent=2))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
