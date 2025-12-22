# AzabBot - Claude Code Instructions

## Project Overview
Discord prison/punishment management bot for server moderation.

## VPS Deployment Rules (CRITICAL)

**NEVER do these:**
- `nohup python main.py &` - creates orphaned processes
- `rm -f /tmp/azab_bot.lock` - defeats single-instance lock
- `pkill` followed by manual start - use systemctl instead

**ALWAYS do these:**
- Use `systemctl restart azabbot.service` to restart
- Use `systemctl stop azabbot.service` to stop
- Use `systemctl status azabbot.service` to check status

## VPS Connection
- Host: `root@188.245.32.205`
- SSH Key: `~/.ssh/hetzner_vps`
- Bot path: `/root/AzabBot`

## Health Check
- Port: 8081
- Test: `curl http://188.245.32.205:8081/health`

## Other Bots on Same VPS
- OthmanBot: port 8080, `systemctl othmanbot.service`
- JawdatBot: port 8082, `systemctl jawdatbot.service`
- TahaBot: port 8083, `systemctl tahabot.service`
- TrippixnBot: port 8086, `systemctl trippixnbot.service`

## Lock Mechanism
- Lock file: `/tmp/azab_bot.lock`
- Contains PID of running process
- Prevents multiple instances
- NEVER delete this file manually

## Key Files
- Config: `src/core/config.py`
- Main entry: `main.py`

## Uploading Code Changes
1. Edit files locally
2. `scp -i ~/.ssh/hetzner_vps <file> root@188.245.32.205:/root/AzabBot/<path>`
3. `ssh -i ~/.ssh/hetzner_vps root@188.245.32.205 "systemctl restart azabbot.service"`

## After Deployment
- Verify: `systemctl status azabbot.service`
- Health: `curl http://188.245.32.205:8081/health`
