# Contributing to Repo Roast

Thank you for your interest in contributing!

## Local Development Setup

To ensure code quality and consistency, we use `pre-commit` hooks. Please install them before committing your changes.

### 1. Install pre-commit
If you haven't already, install pre-commit globally or in your virtual environment:
```bash
pip install pre-commit
```

### 2. Install the hooks
Run the following command in the repository root to install the git hooks:
```bash
pre-commit install
```

Now, `pre-commit` will automatically run on every commit to lint your code and fix basic issues.

### Manual Run
You can manually run all pre-commit hooks on all files at any time:
```bash
pre-commit run --all-files
```
