# Discord Webhook Setup for GitHub Actions

This guide explains how to set up Discord webhooks for GitHub Actions notifications in SaydnayaBot.

## 📋 Prerequisites

- Admin access to your Discord server
- Admin access to your GitHub repository

## 🔧 Step 1: Create Discord Webhook

1. **Open Discord Server Settings**
   - Right-click on your server name
   - Select "Server Settings"

2. **Navigate to Webhooks**
   - In the left sidebar, click "Integrations"
   - Click on "Webhooks"

3. **Create New Webhook**
   - Click "New Webhook" button
   - Give it a name (e.g., "GitHub Actions")
   - Select the channel for notifications (e.g., #dev-notifications)
   - Optionally customize the avatar

4. **Copy Webhook URL**
   - Click "Copy Webhook URL"
   - **Important**: Keep this URL secret!

## 🔐 Step 2: Add Webhook to GitHub Secrets

1. **Go to Repository Settings**
   - Navigate to your repository on GitHub
   - Click "Settings" tab

2. **Access Secrets**
   - In the left sidebar, expand "Secrets and variables"
   - Click "Actions"

3. **Add New Secret**
   - Click "New repository secret"
   - Name: `DISCORD_WEBHOOK`
   - Value: Paste your webhook URL (without any modifications)
   - Click "Add secret"

## 🎨 Notification Types

The workflows will send different types of notifications:

### CI Notifications
- **✅ Tests Passed**: Green embed when all tests pass
- **❌ Tests Failed**: Red embed when tests fail
- **🔒 Security Clean**: Green embed when security scans pass
- **⚠️ Security Issues**: Orange embed when vulnerabilities found

### Deployment Notifications
- **🚀 Deployment Success**: Green embed with deployment details
- **❌ Deployment Failed**: Red embed with error information
- **@here mention**: For critical failures

### Release Notifications
- **📦 New Release**: Blue embed with download links
- **@everyone mention**: To announce new versions
- Includes Docker pull commands and release notes

## 🎯 Webhook Message Format

The notifications use Discord embeds with:
- **Color coding** for status (green/red/orange/blue)
- **Rich formatting** with markdown
- **Clickable links** to GitHub Actions runs
- **Mentions** for critical events
- **Timestamps** for tracking

## 🧪 Testing the Webhook

To test your webhook manually:

```bash
curl -H "Content-Type: application/json" \
     -X POST \
     -d '{"content": "Test message from GitHub Actions"}' \
     YOUR_WEBHOOK_URL
```

## 🔍 Troubleshooting

### Webhook not working
- Verify the webhook URL is correct in GitHub secrets
- Check if the webhook is enabled in Discord
- Ensure the bot has permissions to post in the channel

### No notifications received
- Check GitHub Actions logs for errors
- Verify the workflow syntax is correct
- Ensure the secret name matches `DISCORD_WEBHOOK`

### Rate limiting
- Discord webhooks have a rate limit of 30 requests per minute
- The workflows are designed to respect these limits

## 📊 Monitoring

You can monitor webhook activity in Discord:
1. Go to Server Settings > Integrations > Webhooks
2. Click on your webhook
3. View recent messages sent

## 🔒 Security Notes

- **Never commit webhook URLs** to your repository
- Use GitHub Secrets for all sensitive data
- Rotate webhook URLs periodically
- Delete unused webhooks

## 🎨 Customization

You can customize notifications by editing the workflow files:
- Change colors using hex codes
- Modify message content and formatting
- Add or remove mention types
- Include additional context or metrics

## 🏛️ Forum Channel Support

Discord forum channels require special handling for webhooks:

### Creating Webhook in Forum Channel

1. **Navigate to Forum Channel**
   - Right-click on your forum channel
   - Select "Edit Channel" > "Integrations" > "Webhooks"

2. **Webhook Behavior in Forums**
   - Each webhook message creates a new thread by default
   - You can post to existing threads using `thread_id` parameter

### Configuration Options

#### Option 1: Create New Thread for Each Run
- Webhook will create a new thread for each GitHub Action run
- Thread title will be auto-generated based on the workflow

#### Option 2: Post to Specific Thread
1. Create a thread in your forum channel for CI notifications
2. Get the thread ID (right-click thread > Copy ID)
3. Add to GitHub Secrets:
   - `DISCORD_CI_THREAD_ID`: Thread ID for CI notifications
   - `DISCORD_DEPLOY_THREAD_ID`: Thread ID for deployments
   - `DISCORD_RELEASE_THREAD_ID`: Thread ID for releases

#### Option 3: Organized by Type
Create separate threads for different notification types:
- "🧪 CI Tests" - All test results
- "🚀 Deployments" - Deployment notifications
- "📦 Releases" - New version announcements
- "🔒 Security" - Security scan results

### Using Forum-Compatible Workflows

Use the forum-specific workflows:
```yaml
# .github/workflows/ci.yml
- name: Notify Discord Forum
  env:
    WEBHOOK_URL: ${{ secrets.DISCORD_WEBHOOK }}
    THREAD_ID: ${{ secrets.DISCORD_CI_THREAD_ID }}
  run: |
    # Webhook with thread_id parameter
    curl -X POST "${WEBHOOK_URL}?thread_id=${THREAD_ID}" ...
```

### Thread Management

#### Auto-Archive Settings
- Set forum channel auto-archive to 1 week for CI/CD threads
- Keep release threads permanently

#### Thread Naming Convention
- CI: `CI Run #123 - main`
- Deploy: `Deploy v1.5.0 to production`
- Release: `Release v1.5.0`

### Benefits of Forum Channels

1. **Organization**: Each run gets its own thread
2. **Discussion**: Team can discuss issues in threads
3. **History**: Easy to find past runs
4. **Filtering**: Use tags to categorize (success/failure/deployment)
5. **Search**: Forum search to find specific runs

## 📚 Related Documentation

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Discord Webhooks Guide](https://discord.com/developers/docs/resources/webhook)
- [Discord Forum Channels](https://support.discord.com/hc/en-us/articles/6208479917079-Forum-Channels)
- [Actions Status Discord](https://github.com/marketplace/actions/actions-status-discord)