#!/usr/bin/env python3
"""Check supplied vehicle measurements; no Blender dependency or aesthetic scoring."""
import argparse
import json
import math
from pathlib import Path

LIMITATION = ('Numerical checks of supplied measurements only; not artistic quality, '
              'reference authenticity, camera calibration, or a Blender execution test.')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def number(value, label, minimum=None):
    require(type(value) in (int, float), f'{label} must be a finite number, not a boolean.')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    require(finite, f'{label} must be finite.')
    if minimum is not None:
        require(value >= minimum, f'{label} must be >= {minimum}.')
    return float(value)


def vector(value, count, label):
    require(isinstance(value, list) and len(value) == count, f'{label} must have {count} coordinates.')
    return [number(v, f'{label}[{i}]') for i, v in enumerate(value)]


def common(data):
    require(isinstance(data, dict), 'Input must be an object.')
    require(type(data.get('schema_version')) is int and data['schema_version'] == 1, 'schema_version must be 1.')
    require(nonempty(data.get('model_version')), 'model_version must identify the measured source.')
    require(nonempty(data.get('tolerance_basis')), 'tolerance_basis must explain the chosen thresholds.')


def within(error, tolerance):
    # Numerical roundoff only, never a scene-space margin. Zero tolerance stays exact.
    return error <= tolerance or (tolerance > 0 and math.isclose(error, tolerance, rel_tol=1e-12, abs_tol=0.0))


def landmarks(data):
    common(data)
    for field in ('reference_version', 'view', 'alignment_note'):
        require(nonempty(data.get(field)), f'{field} is required.')
    require(data.get('alignment_confirmed') is True, 'Confirm projection, orientation, crop, and framing alignment first.')
    reference_size = vector(data.get('reference_size'), 2, 'reference_size')
    model_size = vector(data.get('model_size'), 2, 'model_size')
    require(all(v > 0 for v in reference_size + model_size), 'Image dimensions must be positive.')
    require(math.isclose(reference_size[0] / reference_size[1], model_size[0] / model_size[1], rel_tol=1e-9),
            'Image aspect ratios differ; align framing instead of hiding the mismatch.')
    tolerance = number(data.get('tolerance_px'), 'tolerance_px', 0)
    points = data.get('landmarks')
    require(isinstance(points, list) and points, 'At least one actual landmark correspondence is required.')
    rows, identifiers = [], set()
    for point in points:
        require(isinstance(point, dict), 'Each landmark must be an object.')
        identifier = point.get('id')
        require(nonempty(identifier) and identifier not in identifiers, 'Landmark IDs must be nonempty and unique.')
        identifiers.add(identifier)
        ref = vector(point.get('reference_px'), 2, f'{identifier}.reference_px')
        model = vector(point.get('model_px'), 2, f'{identifier}.model_px')
        require(all(0 <= p <= size for p, size in zip(ref, reference_size)), f'{identifier} reference point is outside its frame.')
        require(all(0 <= p <= size for p, size in zip(model, model_size)), f'{identifier} model point is outside its frame.')
        projected = [model[i] / model_size[i] * reference_size[i] for i in range(2)]
        error = math.dist(ref, projected)
        threshold = number(point.get('tolerance_px', tolerance), f'{identifier}.tolerance_px', 0)
        rows.append({'id': identifier, 'error_px': error, 'tolerance_px': threshold,
                     'within_tolerance': within(error, threshold), 'model_in_reference_px': projected})
    return {'status': 'within-tolerances' if all(row['within_tolerance'] for row in rows) else 'needs-correction',
            'model_version': data['model_version'], 'reference_version': data['reference_version'],
            'view': data['view'], 'landmarks': rows,
            'max_error_px': max(row['error_px'] for row in rows),
            'limitation': LIMITATION}


def assemblies(data):
    common(data)
    for key in ('units', 'coordinate_frame'):
        require(nonempty(data.get(key)), f'{key} is required; do not mix coordinate systems.')
    parts = data.get('assemblies')
    require(isinstance(parts, list) and parts, 'assemblies must be a nonempty list.')
    dimensions, rows = {}, []
    for part in parts:
        require(isinstance(part, dict), 'Each assembly must be an object.')
        identifier = part.get('id')
        require(nonempty(identifier) and identifier not in dimensions, 'Assembly IDs must be unique and nonempty.')
        measured = vector(part.get('measured_dimensions'), 3, f'{identifier}.measured_dimensions')
        require(all(v > 0 for v in measured), 'Measured assembly dimensions must be positive.')
        dimensions[identifier] = measured
        if part.get('target_dimensions') is not None:
            target = vector(part['target_dimensions'], 3, f'{identifier}.target_dimensions')
            require(all(v > 0 for v in target), 'Target dimensions must be positive.')
            tolerances = vector(part.get('dimension_tolerance'), 3, f'{identifier}.dimension_tolerance')
            require(all(v >= 0 for v in tolerances), 'Dimension tolerances cannot be negative.')
            for axis in range(3):
                delta = abs(measured[axis] - target[axis])
                rows.append({'id': f'dimension:{identifier}:{axis}', 'actual': measured[axis],
                             'target': target[axis], 'error': delta, 'tolerance': tolerances[axis],
                             'within_tolerance': within(delta, tolerances[axis])})

    attachments = data.get('attachments', [])
    require(isinstance(attachments, list), 'attachments must be a list.')
    identifiers = set()
    for item in attachments:
        require(isinstance(item, dict), 'Each attachment must be an object.')
        identifier = item.get('id')
        require(nonempty(identifier) and identifier not in identifiers, 'Attachment IDs must be unique and nonempty.')
        identifiers.add(identifier)
        for field in ('from_assembly', 'to_assembly'):
            require(nonempty(item.get(field)) and item[field] in dimensions, f'{field} must name a measured assembly.')
        start = vector(item.get('from_position'), 3, f'{identifier}.from_position')
        end = vector(item.get('to_position'), 3, f'{identifier}.to_position')
        target = number(item.get('expected_gap'), f'{identifier}.expected_gap', 0)
        tolerance = number(item.get('tolerance'), f'{identifier}.tolerance', 0)
        actual = math.dist(start, end)
        delta = abs(actual - target)
        rows.append({'id': f'attachment:{identifier}', 'actual': actual, 'target': target,
                     'error': delta, 'tolerance': tolerance, 'within_tolerance': within(delta, tolerance)})

    ratios = data.get('ratios', [])
    require(isinstance(ratios, list), 'ratios must be a list.')
    identifiers = set()
    for item in ratios:
        require(isinstance(item, dict), 'Each ratio must be an object.')
        identifier = item.get('id')
        require(nonempty(identifier) and identifier not in identifiers, 'Ratio IDs must be unique and nonempty.')
        identifiers.add(identifier)
        operands = []
        for field in ('numerator', 'denominator'):
            operand = item.get(field)
            require(isinstance(operand, dict), f'{field} must identify assembly and axis.')
            name, axis = operand.get('assembly'), operand.get('axis')
            require(nonempty(name) and name in dimensions, f'{field} names an unknown assembly.')
            require(type(axis) is int and axis in (0, 1, 2), f'{field}.axis must be 0, 1, or 2.')
            operands.append(dimensions[name][axis])
        target = number(item.get('target_ratio'), f'{identifier}.target_ratio', 0)
        require(target > 0, 'Target ratio must be positive.')
        tolerance = number(item.get('relative_tolerance'), f'{identifier}.relative_tolerance', 0)
        actual = operands[0] / operands[1]
        delta = abs(actual / target - 1)
        rows.append({'id': f'ratio:{identifier}', 'actual': actual, 'target': target,
                     'relative_error': delta, 'relative_tolerance': tolerance,
                     'within_tolerance': within(delta, tolerance)})
    require(rows, 'No numerical acceptance checks supplied; unknown targets are not passes.')
    failed = sum(not row['within_tolerance'] for row in rows)
    return {'status': 'needs-correction' if failed else 'within-tolerances',
            'model_version': data['model_version'], 'units': data['units'],
            'coordinate_frame': data['coordinate_frame'], 'checks': rows,
            'checks_failed': failed, 'limitation': LIMITATION}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['landmarks', 'assemblies'])
    parser.add_argument('input', type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding='utf-8'))
        report = landmarks(data) if args.command == 'landmarks' else assemblies(data)
        encoded = json.dumps(report, indent=2, allow_nan=False)
    except (OSError, ValueError, OverflowError, RecursionError) as exc:
        print(json.dumps({'status': 'input-error', 'errors': [str(exc)], 'limitation': LIMITATION}))
        return 2
    print(encoded)
    return 0 if report['status'] == 'within-tolerances' else 1


if __name__ == '__main__':
    raise SystemExit(main())
