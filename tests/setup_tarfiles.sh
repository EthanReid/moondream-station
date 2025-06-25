#!/usr/bin/env bash
set -euo pipefail
echo "Building test versions for update testing..."
mkdir -p tar_files
cd ../app

echo "=== Building v0.0.2 (clean build) with localhost manifest ==="
bash build.sh dev ubuntu --build-clean
echo "=== Copying and renaming to v002 ==="
for f in ../output/*.tar.gz; do
    [ -e "$f" ] || continue
    base=$(basename "$f" .tar.gz)
    cp "$f" "../tests/tar_files/${base}_v002.tar.gz"
done

echo "=== Building v0.0.1 with localhost manifest ==="
bash build.sh dev ubuntu --build-clean
echo "=== Copying and renaming to v001 ==="
for f in ../output/*.tar.gz; do
    [ -e "$f" ] || continue
    base=$(basename "$f" .tar.gz)
    cp "$f" "../tests/tar_files/${base}_v001.tar.gz"
done

echo "=== Build complete! ==="
echo "Files in tar_files:"
ls -la ../tests/tar_files/
echo ""
echo "Ready for testing with v0.0.1 dev environment installed (pointing to localhost)."