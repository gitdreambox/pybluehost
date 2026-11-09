#!/usr/bin/env bash
# Normalize line endings of staged/modified tracked files to match HEAD.
# The editor on Windows writes CRLF even into LF files; without .gitattributes
# the repo convention is "keep whatever the file had". Run before committing.
set -euo pipefail
changed=0
for f in $(git diff --name-only HEAD -- '*.py' '*.md' '*.yaml' '*.yml' '*.sh' '*.txt' 2>/dev/null); do
    [ -f "$f" ] || continue
    # HEAD version's first line ending decides the target.
    if git show "HEAD:$f" 2>/dev/null | head -c 4096 | grep -q $'\r'; then
        target=crlf
    else
        target=lf
    fi
    if [ "$target" = lf ]; then
        if head -c 4096 "$f" | grep -q $'\r'; then
            python -c "import sys;f='$f';d=open(f,'rb').read();open(f,'wb').write(d.replace(b'\r\n',b'\n'))"
            echo "LF-normalized: $f"; changed=1
        fi
    else
        if ! head -c 4096 "$f" | grep -q $'\r'; then
            python -c "import sys;f='$f';d=open(f,'rb').read();open(f,'wb').write(d.replace(b'\n',b'\r\n'))"
            echo "CRLF-normalized: $f"; changed=1
        fi
    fi
done
[ "$changed" = 0 ] && echo "line endings OK"
exit 0
