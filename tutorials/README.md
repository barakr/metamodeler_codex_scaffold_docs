# Tutorials folder

Start here:
- `tutorials/Tutorial_0.ipynb`

Then run:
- `tutorials/Tutorial_1.ipynb` through `tutorials/Tutorial_9.ipynb`

## Cross-platform setup (Windows / macOS / Linux)

The tutorials are notebook-portable: every notebook starts with a self-contained
bootstrap cell that locates the repo root, puts `src/` on `sys.path`, and defines
in-notebook helpers (`run_mm_cli`, `run_tool`). There are no `%%bash` cells and no
`PYTHONPATH=src` prefixes, so they run identically on Windows cmd, Windows
PowerShell, macOS, and Linux.

### Install once (pick one)
**conda (recommended):**
```
conda env create -f environment.yml
conda activate py314_bayesmm
```
**pip + venv:**
```
python -m venv .venv
# bash/zsh:            source .venv/bin/activate
# Windows PowerShell:  .venv\Scripts\Activate.ps1
# Windows cmd:         .venv\Scripts\activate.bat
pip install -e ".[pymc,sbi]" jupyter matplotlib
```

### Verify your environment
```
bayesmm doctor
```
If a backend is missing, run `bayesmm setup` for guided, OS-correct install commands.

## Notes
- Each notebook includes prerequisites, estimated time, success criteria, and troubleshooting.
- Each notebook includes at least one visual checkpoint (plot/graphic).
- Tutorials are mostly standalone; serial execution is also supported.
- Tutorial 1 uses centralized sweep artifacts (`sweep_rows.csv`) to visualize toy outputs.
- Tutorials 5 and 6 require `pymc` and `sbi` respectively (use `bayesmm doctor` to confirm).
