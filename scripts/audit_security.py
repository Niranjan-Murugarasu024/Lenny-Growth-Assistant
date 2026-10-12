"""
Security audit script for The Lenny Growth Assistant.
Scans Git commits, working tree, configuration files, and environment templates.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

SECRET_PATTERNS = [
    (re.compile(r'(?i)api[_-]?key\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']'), 'API Key'),
    (re.compile(r'(?i)secret[_-]?token\s*[:=]\s*["\']([a-zA-Z0-9_\-]{20,})["\']'), 'Secret Token'),
    (re.compile(r'sk-[a-zA-Z0-9]{32,}'), 'OpenAI API Key'),
    (re.compile(r'ghp_[a-zA-Z0-9]{36}'), 'GitHub PAT'),
    (re.compile(r'BEGIN (?:RSA |EC )?PRIVATE KEY'), 'Private Key'),
    (re.compile(r'(?i)postgres(?:ql)?:\/\/[a-zA-Z0-9_-]+:([a-zA-Z0-9_\-!@#$%^&*]+)@'), 'PostgreSQL Password in URI'),
]

IGNORE_DIRS = {'.git', '.venv', 'venv', 'node_modules', 'dist', '__pycache__', '.pytest_cache'}
IGNORE_FILES = {'.env', '.env.txt', 'package-lock.json', 'impeccable.exe'}


def audit_git_history() -> list[str]:
    findings = []
    res = subprocess.run(['git', 'log', '-p', '--all'], capture_output=True, text=True, errors='ignore')
    for line in res.stdout.splitlines():
        if line.startswith('+') and not line.startswith('+++'):
            for pattern, label in SECRET_PATTERNS:
                if pattern.search(line):
                    # Sanitize: don't print line content, just detection
                    findings.append(f'Git History: potential {label}')
    return findings


def audit_working_tree() -> list[dict[str, str]]:
    findings = []
    root_path = Path('.')
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            if f in IGNORE_FILES:
                continue
            fpath = Path(root) / f
            # Skip binary or very large files
            if fpath.suffix in {'.png', '.jpg', '.jpeg', '.webp', '.ico', '.exe', '.tar', '.tgz'}:
                continue
            try:
                content = fpath.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue

            for pattern, label in SECRET_PATTERNS:
                if 'conftest' in f.lower() or 'test_' in f.lower() or '.example' in f.lower():
                    continue
                matches = pattern.findall(content)
                if matches:
                    findings.append({
                        'file': str(fpath),
                        'category': label,
                        'count': len(matches),
                    })
    return findings


def main():
    print("Auditing Git history...")
    git_findings = audit_git_history()
    print(f"Git history secret findings: {len(git_findings)}")
    for gf in set(git_findings):
        print(f" - {gf}")

    print("\nAuditing working tree...")
    tree_findings = audit_working_tree()
    print(f"Working tree findings: {len(tree_findings)}")
    for tf in tree_findings:
        print(f" - {tf['file']}: {tf['category']} ({tf['count']} occurrences)")


if __name__ == '__main__':
    main()
