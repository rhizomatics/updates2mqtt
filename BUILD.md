# Build

## Test

### Integration / Smoke Tests

```bash
uv run pytest tests --integration --runslow
```

## Release

```bash
UV_NO_CONFIG=1 uv version 1.X.Y
```