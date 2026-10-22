#!/usr/bin/env python3
"""Display controlled render evidence; never judge artwork or execute Blender."""
import argparse
import base64
import binascii
import hashlib
import html
import json
import math
from pathlib import Path, PureWindowsPath
import re
import struct
import sys


def require(condition, message):
    if not condition:
        raise ValueError(message)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def check_digest(value, field):
    require(isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None,
            '%s must be a lowercase 64-character SHA256' % field)


def file_digest(path, field):
    try:
        require(path.is_file(), '%s must name an existing regular file: %s' % (field, path))
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError as exc:
        raise ValueError('%s: %s' % (field, exc)) from exc


def validate_metadata(manifest):
    require(isinstance(manifest, dict), 'manifest must be a JSON object')
    require(type(manifest.get('schema_version')) is int and manifest['schema_version'] == 1,
            'schema_version must be integer 1')
    source = manifest.get('source_path')
    require(text(source) and Path(source).is_absolute(), 'source_path must be an absolute file path')
    for field in ('source_sha256', 'rig_sha256', 'tool_sha256'):
        check_digest(manifest.get(field), field)
    require(file_digest(Path(source), 'source_path') == manifest['source_sha256'],
            'source_sha256 does not match current source file bytes: %s' % source)
    require(type(manifest.get('frame')) is int, 'frame must be an integer')
    for field in ('blender_version', 'render_engine'):
        require(text(manifest.get(field)), '%s must be a nonempty string' % field)
    cameras = manifest.get('camera_matrices')
    require(isinstance(cameras, dict) and bool(cameras), 'camera_matrices must be a nonempty object')
    for view, matrix in cameras.items():
        require(text(view) and isinstance(matrix, list) and len(matrix) == 4 and
                all(isinstance(row, list) and len(row) == 4 and
                    all(type(value) is int or (type(value) is float and math.isfinite(value))
                        for value in row) for row in matrix),
                'camera_matrices must contain finite numeric 4x4 matrices: %s' % view)


def image_path(directory, raw):
    require(text(raw), 'image path must be a nonempty relative string')
    require(not Path(raw).is_absolute() and not PureWindowsPath(raw).drive and
            not any(char in raw for char in ('\\', ':', '\x00')) and
            all(part not in ('', '.', '..') for part in raw.split('/')),
            'unsafe image path (absolute or traversal syntax): %r' % raw)
    try:
        resolved = (directory / raw).resolve(strict=True)
        require(directory in resolved.parents,
                'image path escapes manifest directory: %r' % raw)
        require(resolved.is_file(), 'image path is not a regular file: %r' % raw)
        return resolved
    except (OSError, RuntimeError) as exc:
        raise ValueError('image path %r: %s' % (raw, exc)) from exc


def png_size(data, name):
    require(len(data) >= 33 and data[:8] == b'\x89PNG\r\n\x1a\n' and
            data[8:16] == b'\x00\x00\x00\rIHDR',
            'invalid or truncated PNG IHDR header: %s' % name)
    require(binascii.crc32(data[12:29]) & 0xffffffff == struct.unpack('>I', data[29:33])[0],
            'invalid PNG IHDR CRC: %s' % name)
    width, height = struct.unpack('>II', data[16:24])
    require(0 < width <= 0x7fffffff and 0 < height <= 0x7fffffff,
            'invalid PNG dimensions: %s' % name)
    return width, height


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, 'duplicate JSON object key: %s' % key)
        result[key] = value
    return result


def load_review(path):
    path = Path(path).resolve(strict=True)
    require(path.is_file(), 'manifest must be a regular file: %s' % path)
    manifest = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    validate_metadata(manifest)
    require(file_digest(path.parent / 'rig-lock.json', 'rig-lock.json') == manifest['rig_sha256'],
            'rig_sha256 does not match adjacent rig-lock.json bytes: %s' % path.parent)
    rows = manifest.get('images')
    require(isinstance(rows, list) and bool(rows), 'images must be a nonempty list')
    images = {}
    for index, row in enumerate(rows):
        require(isinstance(row, dict), 'images[%s] must be an object' % index)
        for field in ('view', 'mode'):
            require(text(row.get(field)), 'images[%s].%s must be a nonempty string' % (index, field))
        require(row['view'] in manifest['camera_matrices'],
                'camera_matrices missing image view %r' % row['view'])
        size = row.get('frame_size')
        require(isinstance(size, list) and len(size) == 2 and
                all(type(value) is int and 0 < value <= 0x7fffffff for value in size),
                'images[%s].frame_size must contain two positive PNG integer dimensions' % index)
        key = (row['view'], row['mode'], tuple(size))
        require(key not in images, 'duplicate image pair (view, mode, frame_size): %r' % (key,))
        check_digest(row.get('sha256'), 'images[%s].sha256' % index)
        resolved = image_path(path.parent, row.get('path'))
        data = resolved.read_bytes()
        require(hashlib.sha256(data).hexdigest() == row['sha256'],
                'image sha256 does not match current image bytes: %s' % resolved)
        require(png_size(data, resolved) == tuple(size),
                'PNG dimensions do not match frame_size: %s' % resolved)
        images[key] = (row, data)
    return manifest, images


def validate_comparison(before, after):
    for field in ('rig_sha256', 'tool_sha256', 'camera_matrices', 'frame', 'render_engine', 'blender_version'):
        require(before[0][field] == after[0][field],
                '%s mismatch: not a controlled comparison' % field)
    require(before[1].keys() == after[1].keys(),
            'image pair sets differ (view, mode, frame_size): not a controlled comparison')


def comparison_html(before, after):
    escape = lambda value: html.escape(str(value), quote=True)
    first, second = before[0], after[0]
    parts = ['<!doctype html><html lang="en"><meta charset="utf-8">',
             '<meta name="viewport" content="width=device-width, initial-scale=1">',
             '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
             'img-src data:; style-src \'unsafe-inline\'; base-uri \'none\'; form-action \'none\'">',
             '<title>Before / after render review</title><style>',
             'body{font:16px system-ui,sans-serif;margin:24px;background:#181a1e;color:#eee}'
             'code{overflow-wrap:anywhere}section{margin:28px 0}.pair{display:flex;gap:20px;overflow-x:auto}'
             'figure{margin:0;flex:0 0 auto}figcaption{margin:8px 0}'
             'img{display:block;height:auto}.full{max-width:min(640px,80vw)}'
             '.preview{max-width:none}dt{font-weight:bold}dd{margin-bottom:12px}',
             '</style><body><h1>Before / after render review</h1>',
             '<p>Controlled evidence display, not an aesthetic score or a claim of image-content correctness. '
             'A person must assess the artwork. Preview dimensions describe the frame, not vehicle pixel height.</p>',
             '<dl>']
    for label, manifest in [('Before', first), ('After', second)]:
        parts.append('<dt>%s source</dt><dd>%s<br>SHA256: <code>%s</code></dd>' %
                     (label, escape(manifest['source_path']), escape(manifest['source_sha256'])))
    for field in ('rig_sha256', 'tool_sha256', 'blender_version', 'render_engine', 'frame'):
        parts.append('<dt>%s</dt><dd><code>%s</code></dd>' % (escape(field), escape(first[field])))
    parts.append('</dl>')
    maxima = {}
    for view, mode, size in before[1]:
        maxima[(view, mode)] = max(maxima.get((view, mode), 0), size[0] * size[1])
    for key in sorted(before[1]):
        view, mode, (width, height) = key
        preview = width * height < maxima[(view, mode)]
        kind = 'preview' if preview else 'full'
        parts.append('<section><h2>%s / %s — %s × %s (%s)</h2><div class="pair">' %
                     (escape(view), escape(mode), width, height, kind))
        for label, review in [('Before', before), ('After', after)]:
            row, data = review[1][key]
            parts.append('<figure><figcaption>%s — %s</figcaption>'
                         '<img class="%s" width="%s" height="%s" alt="%s" '
                         'src="data:image/png;base64,%s"></figure>' %
                         (label, escape(row['path']), kind, width, height,
                          escape('%s %s %s %sx%s' % (label, view, mode, width, height)),
                          base64.b64encode(data).decode('ascii')))
        parts.append('</div></section>')
    parts.append('</body></html>\n')
    return ''.join(parts)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('before', help='before render-manifest.json')
    parser.add_argument('after', help='after render-manifest.json')
    parser.add_argument('--output', required=True, help='new self-contained HTML file (never overwritten)')
    args = parser.parse_args(argv)
    try:
        output = Path(args.output)
        require(not output.exists() and not output.is_symlink(),
                'output already exists; refusing to overwrite: %s' % output)
        before, after = load_review(args.before), load_review(args.after)
        validate_comparison(before, after)
        document = comparison_html(before, after)
        try:
            # Exclusive creation also blocks a file/symlink appearing after the check.
            with output.open('x', encoding='utf-8', newline='\n') as stream:
                stream.write(document)
        except OSError as exc:
            raise ValueError('output %s: %s' % (output, exc)) from exc
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        print('compare_reviews: %s' % exc, file=sys.stderr)
        return 1
    print('Wrote %s' % args.output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
