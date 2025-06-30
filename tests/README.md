# Moondream Station Testing

## Prerequisites

- Python 3.10
- Two manifest JSON files (base and test versions)
- Expect executable in ../output/moondream_station/

### Install Python Requirements
First, ensure you are in the moondream-station repo.
Then, to install the requirements, execute:
```
cd tests
pip install -r requirements.txt
```
## Usage
To test all components one by one, we can use the following command:

```
python test_update.py --base-manifest manifest_v1.json --test-manifest manifest_v2.json
```
To test a specific component, we can specify the component using the `--test` flag.

Additionally, if we want to enable capability checks (query, caption, detect, point) at the end of the test, enable `--with-capability`.
```
python test_update.py --base-manifest base.json --test-manifest test.json --test inference,hypervisor --with-capability
```

## What It Does

1. Builds component tarballs
2. Starts local HTTP server
3. Tests updates from base → test version
4. Verifies components updated correctly
5. (Optional) Tests model capabilities


## Output
- ✅ Success: Component updated correctly
- ❌ Failure: Update failed with error details
- ⏭️ Skipped: No version change detected

## Notes
- When running the tests, make sure that at least one of the models support the latest inference client in the manifest.
- When adding an inference client to the test manifest, please make sure that the original inference client(s) in the base manifest are also supported.