# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.0.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability in SaydnayaBot, please follow these steps:

1. **DO NOT** open a public issue on GitHub
2. Send a detailed report to the maintainers via private message
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will acknowledge receipt within 48 hours and provide a detailed response within 7 days.

## Security Best Practices

When using SaydnayaBot:

1. **Never commit sensitive data:**
   - Keep your `.env` file private
   - Never share your Discord token or OpenAI API key
   - Use `.env.example` as a template

2. **Permissions:**
   - Only grant the minimum Discord permissions needed
   - Restrict bot access to appropriate channels only
   - Only trusted users should have the developer ID

3. **API Keys:**
   - Rotate API keys regularly
   - Use separate keys for development and production
   - Monitor API usage for anomalies

4. **Updates:**
   - Keep dependencies up to date
   - Regularly check for security advisories
   - Apply security patches promptly

## Responsible Disclosure

We appreciate security researchers who follow responsible disclosure practices. We commit to:
- Not pursuing legal action against researchers who follow this policy
- Acknowledging researchers in our security updates (if desired)
- Working collaboratively to fix vulnerabilities