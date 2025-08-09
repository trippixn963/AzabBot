# Contributing to SaydnayaBot

Thank you for your interest in contributing to SaydnayaBot! This document provides guidelines for contributing to the project.

## Code of Conduct

By participating in this project, you agree to abide by our Code of Conduct (see CODE_OF_CONDUCT.md).

## How to Contribute

### Reporting Issues

- Use the GitHub issue tracker to report bugs
- Check if the issue already exists before creating a new one
- Provide detailed information about the issue:
  - Steps to reproduce
  - Expected behavior
  - Actual behavior
  - System information (Python version, OS, etc.)

### Suggesting Features

- Open an issue with the "enhancement" label
- Clearly describe the feature and its use case
- Be open to discussion and feedback

### Pull Requests

1. Fork the repository
2. Create a new branch (`git checkout -b feature/amazing-feature`)
3. Make your changes
4. Run tests and ensure code quality:
   ```bash
   poetry run pre-commit run --all-files
   poetry run pytest
   ```
5. Commit your changes (`git commit -m 'Add amazing feature'`)
6. Push to the branch (`git push origin feature/amazing-feature`)
7. Open a Pull Request

## Development Setup

1. Install Poetry:
   ```bash
   curl -sSL https://install.python-poetry.org | python3 -
   ```

2. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/saydnayabot.git
   cd saydnayabot
   ```

3. Install dependencies:
   ```bash
   poetry install
   ```

4. Install pre-commit hooks:
   ```bash
   poetry run pre-commit install
   ```

## Code Standards

- Follow PEP 8 guidelines
- Use type hints where appropriate
- Write docstrings for all public functions and classes
- Keep functions focused and small
- Write tests for new features

### Code Formatting

We use the following tools to maintain code quality:
- **black** - Code formatting
- **isort** - Import sorting
- **flake8** - Linting
- **ruff** - Fast Python linting
- **mypy** - Type checking (optional)

Run all checks:
```bash
poetry run pre-commit run --all-files
```

## Testing

- Write tests for new features
- Ensure all tests pass before submitting PR
- Aim for high test coverage
- Use pytest for testing

```bash
poetry run pytest
poetry run pytest --cov=src  # with coverage
```

## Documentation

- Update README.md if needed
- Add docstrings to new functions/classes
- Update documentation for configuration changes
- Include examples where helpful

## Commit Messages

- Use clear and descriptive commit messages
- Start with a verb (Add, Fix, Update, etc.)
- Keep the first line under 50 characters
- Add detailed description if needed

Examples:
- `Add user authentication feature`
- `Fix rate limiting in prison channels`
- `Update documentation for configuration`

## Questions?

Feel free to open an issue for any questions about contributing.