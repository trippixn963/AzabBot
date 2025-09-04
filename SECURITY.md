# 🔒 Azab Discord Bot - Security Policy

<div align="center">

**Security considerations for the Azab Discord Bot**

*Built specifically for discord.gg/syria*

</div>

---

## 🛡️ Data Handling

### What Data is Stored
- **User Messages**: Stored locally in SQLite database
- **User IDs**: For tracking and identification  
- **Interaction History**: For AI response context
- **Mute Reasons**: Extracted from Discord embeds

### Data Privacy
- **Local Storage**: All data stored locally, not sent to external servers
- **No Personal Info**: Only Discord usernames and message content
- **Temporary Data**: Mute reasons stored temporarily for context

---

## ⚠️ Security Warnings

### API Keys
- **Never commit API keys** to version control
- **Use environment variables** for sensitive data
- **Rotate keys regularly** for security

### Discord Permissions
- **Minimal Permissions**: Bot only requests necessary permissions
- **Channel Restrictions**: Can be limited to specific channels
- **Role-Based Access**: Commands require administrator permissions

### Input Validation
- **Message Sanitization**: All user input is validated
- **Length Limits**: Message content is truncated to prevent abuse
- **Rate Limiting**: Built-in cooldowns prevent spam

---

## 🔧 Security Best Practices

### For Users
- **Review Bot Permissions**: Only grant necessary permissions
- **Monitor Bot Activity**: Check logs for unusual behavior
- **Use in Designated Channels**: Limit bot to appropriate channels
- **Regular Updates**: Keep dependencies updated

### For Developers
- **Environment Variables**: Never hardcode sensitive data
- **Input Validation**: Always validate user input
- **Error Handling**: Don't expose sensitive information in errors
- **Logging**: Be careful not to log sensitive data

---

## 📋 Security Checklist

- [ ] API keys stored in environment variables
- [ ] Bot permissions minimized
- [ ] Input validation implemented
- [ ] Rate limiting enabled
- [ ] Error handling secure
- [ ] Logging doesn't expose sensitive data
- [ ] Dependencies updated regularly

---

## 🚨 Reporting Security Issues

**This is a personal project with no support provided.**

If you discover a security vulnerability:

1. **Do NOT create a public issue**
2. **Do NOT post about it publicly**
3. **This project is not maintained**
4. **Use at your own risk**

---

## ⚖️ Legal Notice

This bot is provided for educational purposes only. Users are responsible for:
- Complying with Discord Terms of Service
- Respecting user privacy
- Using the bot responsibly
- Following local laws and regulations

---

<div align="center">

**⭐ Star this repository if you find it useful!**

[Report Issues](https://github.com/trippixn963/AzabBot/issues) • [Discord Server](https://discord.gg/syria)

</div>
