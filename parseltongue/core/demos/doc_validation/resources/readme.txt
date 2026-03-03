# AuthLib

A lightweight authentication library for Python applications.

## Installation

```
pip install authlib
```

Requires Python 3.9 or higher.

## Quick Start

```python
from authlib import TokenManager

manager = TokenManager(algorithm="sha256", expiry=1800)
token = manager.generate(user_id="alice")
```

Tokens are generated using SHA-256 and expire after 30 minutes by default.
The maximum token lifetime is 2 hours (7200 seconds).

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| algorithm | sha256  | Hashing algorithm |
| expiry    | 1800    | Token lifetime in seconds |
| max_sessions | 10  | Maximum concurrent sessions |

## Session Management

Sessions are created automatically on first token generation.
Each session is bound to a single IP address for security.
Session IDs use the same hashing algorithm as tokens (SHA-256).

## Security

All cryptographic operations use SHA-256. The library has been
audited by three independent security firms and contains zero
known vulnerabilities as of version 2.0.
