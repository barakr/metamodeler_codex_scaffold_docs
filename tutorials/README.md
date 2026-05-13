# Tutorials folder

Start here:
- `tutorials/Tutorial_0.ipynb`

Then run:
- `tutorials/Tutorial_1.ipynb` through `tutorials/Tutorial_9.ipynb`

## Cross-platform setup (Windows / macOS / Linux)

The tutorials are notebook-portable: each one calls `metamodeler.tutorial.bootstrap()`
to find the project root and configure `sys.path` automatically. There are no
hardcoded paths.

### Install once (pick one)
**Conda (recommended):**
```
conda env create -f environment.yml
conda activate metamodeler
```

**pip + venv:**
```
python -m venv .venv
# bash / zsh:
source .venv/bin/activate
# Windows PowerShell:
.venv\Scripts\Activate.ps1
# Windows cmd:
.venv\Scripts\activate.bat

pip install -e ".[pymc,sbi]" jupyter matplotlib
```

### Verify your environment
```
mm doctor
```
If a backend is missing, run `mm setup` for guided install commands.

### Run a tutorial
```
jupyter notebook tutorials/Tutorial_1.ipynb
```
or non-interactively:
```
jupyter execute tutorials/Tutorial_1.ipynb
```

## Notes
- Each notebook includes prerequisites, estimated time, success criteria, and troubleshooting.
- Each notebook includes at least one visual checkpoint (plot/graphic).
- Tutorials are mostly standalone; serial execution is also supported.
- Tutorials 5 and 6 require `pymc` and `sbi` respectively (use `mm doctor` to confirm).
