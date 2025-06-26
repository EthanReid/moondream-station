#!/usr/bin/env bash
set -euo pipefail

echo "Building test versions for update testing..."
mkdir -p tar_files
cd ../app

# Only need v0.0.1 and v0.0.2 builds
echo "=== Building v0.0.1 components ==="
bash build.sh hypervisor ubuntu --version="v0.0.1" --build-clean
bash build.sh cli ubuntu --version="v0.0.1"
bash build.sh inference ubuntu --version="v0.0.1"

# Copy v001 files
cp ../output/moondream_station_ubuntu.tar.gz "../tests/tar_files/moondream_station_ubuntu_v001.tar.gz"
cp ../output/hypervisor.tar.gz "../tests/tar_files/hypervisor_v001.tar.gz"
cp ../output/moondream-cli.tar.gz "../tests/tar_files/moondream-cli_v001.tar.gz"
cp ../output/inference_bootstrap.tar.gz "../tests/tar_files/inference_bootstrap_v001.tar.gz"

echo "=== Building v0.0.2 components ==="
bash build.sh hypervisor ubuntu --version="v0.0.2" --build-clean
bash build.sh cli ubuntu --version="v0.0.2"
bash build.sh inference ubuntu --version="v0.0.2"

# Copy v002 files
cp ../output/moondream_station_ubuntu.tar.gz "../tests/tar_files/moondream_station_ubuntu_v002.tar.gz"
cp ../output/hypervisor.tar.gz "../tests/tar_files/hypervisor_v002.tar.gz"
cp ../output/moondream-cli.tar.gz "../tests/tar_files/moondream-cli_v002.tar.gz"
cp ../output/inference_bootstrap.tar.gz "../tests/tar_files/inference_bootstrap_v002.tar.gz"

# Build a dev environment with v0.0.1 (for initial testing)
echo "=== Building dev environment with v0.0.1 ==="
bash build.sh dev ubuntu --build-clean

echo "=== Build complete! ==="
echo "Files in tar_files:"
ls -la ../tests/tar_files/
echo ""
echo "Ready for testing! Dev environment installed with v0.0.1."
echo ""
echo "Test sequence:"
echo "  manifest_v001: all components v0.0.1"
echo "  manifest_v002: bootstrap v0.0.2, rest v0.0.1"
echo "  manifest_v003: bootstrap v0.0.2, hypervisor v0.0.2, rest v0.0.1"
echo "  manifest_v004: model update (same binaries)"
echo "  manifest_v005: cli v0.0.2"
echo "  manifest_v006: inference v0.0.2"