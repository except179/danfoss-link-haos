#!/usr/bin/env python3
"""Bounded public snapshot privacy/packaging preflight; no network or test suite."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

from privacy_audit import BLOCKING, categories, filename_categories

ROOT = Path(__file__).resolve().parents[1]


def main():
    files = sorted(p for p in ROOT.rglob('*') if p.is_file()
                   and not any(part in ('.git', '__pycache__', 'dist') for part in p.relative_to(ROOT).parts))
    errors = []
    links = 0
    python = shell = 0
    for path in files:
        name = str(path.relative_to(ROOT))
        if path.is_symlink():
            errors.append((name, 'symlink'))
            continue
        data = path.read_bytes()
        hits = (categories(data) | filename_categories(name)) & BLOCKING
        if hits:
            errors.append((name, sorted(hits)))
        if b'-----BEGIN CERTIFICATE-----' in data and path.suffix == '.pem' and name != 'danfoss_link/vendor/src/danfoss_mdg/trusted-CAs.pem':
            errors.append((name, 'unexpected certificate bundle'))
        if path.suffix == '.py':
            compile(data, name, 'exec')
            python += 1
        if path.suffix == '.sh':
            subprocess.run(['sh', '-n', str(path)], check=True)
            shell += 1
        if path.suffix == '.json':
            json.loads(data)
        if path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
            if any(marker in data for marker in (b'eXIf', b'tEXt', b'iTXt', b'zTXt', b'Exif\x00\x00')):
                errors.append((name, 'image metadata'))
        if path.suffix == '.md':
            text = data.decode()
            targets = re.findall(r'!?\[[^\]]*\]\(([^\s)]+)\)', text)
            targets += re.findall(r'(?:src|href)="([^"#]+)"', text)
            for target in targets:
                parsed = urlsplit(target.strip('<>'))
                if parsed.scheme or not parsed.path:
                    continue
                destination = (path.parent / unquote(parsed.path)).resolve()
                links += 1
                if not destination.is_relative_to(ROOT) or not destination.exists():
                    errors.append((name, 'missing/outside local link: ' + target))
    config = (ROOT / 'danfoss_link/config.yaml').read_text()
    for value in ('version: "0.3.1"', '  operation: setup', '  mqtt_host: ""',
                  '  mqtt_username: ""', '  mqtt_tls: true', '  danfoss_allow_writes: false'):
        assert value in config
    assert not re.search(r'^image:', config, re.M), 'This release uses Supervisor source builds'
    for name in ('repository.yaml', 'LICENSE', 'danfoss_link/Dockerfile', 'danfoss_link/.dockerignore',
                 'danfoss_link/icon.png', 'danfoss_link/logo.png', 'danfoss_link/translations/en.yaml',
                 'danfoss_link/vendor/LICENSE', 'danfoss_link/vendor/THIRD_PARTY_NOTICES.md'):
        assert (ROOT / name).is_file(), name
    manifest = ROOT / 'metadata/source-sha256.json'
    if manifest.exists():
        for name, digest in json.loads(manifest.read_text()).items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
    print(json.dumps({'status': 'FAIL' if errors else 'PASS', 'files': len(files),
                      'python_syntax': python, 'shell_syntax': shell, 'local_links': links,
                      'errors': errors, 'limit': 'Bounded pattern/path/manual review; not a comprehensive security audit or an installed HAOS test.'}, indent=2))
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
