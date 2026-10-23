#!/usr/bin/env python3
"""Read-only Git/object privacy review. Reports categories and paths, never hits.

Includes all local objects (also reflog-only/dangling/staged objects) and
tracked/non-ignored working files. Does not open ignored credentials/backups.
Exit 2 with --strict when blocking patterns occur. This is a bounded scanner,
not proof of absence; synthetic fixtures and public trust anchors need review.
"""
import argparse
from collections import defaultdict
import ipaddress
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private_key_material': rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----[\r\n]+[A-Za-z0-9+/=]{40}',
    'service_token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[A-Z0-9]{16}|AIza[A-Za-z0-9_-]{30,}|sk-[A-Za-z0-9_-]{30,})',
    'jwt_review': rb'eyJ[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}\.[A-Za-z0-9_-]{12,}',
    'credential_url': rb'[a-z]+://[^\s/:]+:[^\s/@]+@',
    'certificate_fingerprint': rb'(?:[0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}',
    'credential_assignment_review': rb'(?i)(?:password|passwd|token|secret)[\x22\x27]?\s*[=:]\s*[\x22\x27][^\x22\x27\r\n]{3,}',
    'certificate_body_review': rb'-----BEGIN CERTIFICATE-----[\r\n]+[A-Za-z0-9+/=]{40}',
    'operator_path_review': rb'/root/(?:projects/|mqtt-pki/)|/protected/off-device/',
    'local_hostname_review': rb'(?i)\b[a-z0-9_-]+(?:\.[a-z0-9_-]+)*\.(?:lan|local)\b',
    'pairing_payload_review': rb'(?i)[\x22\x27](?:peer_name|certificate_der|pairing_code)[\x22\x27]\s*:',
}
BLOCKING = {'private_key_material', 'service_token', 'credential_url',
            'certificate_fingerprint', 'private_network_reference', 'sensitive_filename'}
NETWORKS = tuple(map(ipaddress.ip_network, ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')))
GENERIC_ADDRESSES = {'10.0.0.0', '172.16.0.0', '192.168.0.0', '172.30.32.2'}

def categories(data):
    found = {name for name, pattern in PATTERNS.items() if re.search(pattern, data)}
    for value in re.findall(rb'(?<![0-9.])(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?![0-9.])', data):
        try:
            ip = ipaddress.ip_address(value.decode())
        except ValueError:
            continue
        if str(ip) not in GENERIC_ADDRESSES and any(ip in net for net in NETWORKS):
            found.add('private_network_reference')
    return found

def filename_categories(name):
    return {'sensitive_filename'} if re.search(r'(?i)(?:^|/)(?:paired_cc\.json|app_key\.pem|app_cert\.pem|options\.json|mqtt_password|\.env)$|\.(?:key|p12|pfx|tar|gpg|bak)$', name) else set()

def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)

def audit(tree_only=False):
    result = defaultdict(lambda: defaultdict(set))
    paths = defaultdict(set)
    commits = git('rev-list', '--all', '--reflog').decode().splitlines()
    if not tree_only:
        for commit in commits:
            for row in git('ls-tree', '-r', commit).decode().splitlines():
                meta, name = row.split('\t', 1)
                _, kind, oid = meta.split()
                if kind == 'blob':
                    paths[oid].add(name)
        inventory = git('cat-file', '--batch-all-objects', '--batch-check=%(objectname) %(objecttype)').decode().splitlines()
    else:
        inventory = []
    counts = defaultdict(int)
    for row in inventory:
        oid, kind = row.split()
        counts[kind] += 1
        if kind not in ('blob', 'commit', 'tag'):
            continue
        data = git('cat-file', kind, oid)
        names = paths[oid] or {f'({kind} without reachable path)'}
        hits = categories(data)
        for name in names:
            for category in hits | filename_categories(name):
                result['history'][category].add(name)
    current = git('ls-files', '--cached', '--others', '--exclude-standard', '-z').decode().split('\0')
    for name in sorted(set(current) - {''}):
        p = ROOT / name
        if not p.is_file() or p.is_symlink():
            continue
        data = p.read_bytes()
        for category in categories(data) | filename_categories(name):
            result['working_tree'][category].add(name)
        if p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp'):
            if any(marker in data for marker in (b'eXIf', b'tEXt', b'iTXt', b'zTXt', b'Exif\x00\x00')):
                result['working_tree']['image_metadata_review'].add(name)
    report = {
        'head': git('rev-parse', 'HEAD').decode().strip(),
        'scope': 'current non-ignored tree' if tree_only else 'current non-ignored tree and ALL local Git objects, including dangling/reflog/index objects',
        'reachable_or_reflog_commits': len(commits),
        'git_object_counts': dict(counts),
        'current_file_count': len(set(current) - {''}),
        'findings': {scope: {k: sorted(v) for k, v in sorted(items.items())} for scope, items in sorted(result.items())},
        'ignored_files': 'not opened; preserve private artifacts/credentials/backups outside publication',
        'limitations': 'Pattern and filename scan; no matched values, secret hashes or binary contents emitted. Public service anchors, synthetic fixtures and possible personal/household context require manual review. No cryptographic proof of secret absence.',
    }
    report['status'] = 'BLOCKED' if any(set(items) & BLOCKING for items in result.values()) else 'REVIEW_REQUIRED'
    return report

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree-only', action='store_true')
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = audit(args.tree_only)
    output = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end='')
    return 2 if args.strict and report['status'] == 'BLOCKED' else 0

if __name__ == '__main__':
    raise SystemExit(main())
