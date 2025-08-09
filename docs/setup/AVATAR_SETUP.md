# Setting Up Custom Bot Avatar

## How to Set the Pixel Art Avatar

The bot will automatically preserve whatever avatar you set as its "original" default avatar.

### Steps:

1. **Upload the pixel art image to Discord:**
   - Go to [Discord Developer Portal](https://discord.com/developers/applications)
   - Select your bot application
   - Go to "Bot" section
   - Click on the bot's avatar area
   - Upload the pixel art image (pfp.gif)
   - Save changes

2. **Restart the bot:**
   - The bot will detect its current avatar as the "original"
   - It will store this URL for future restoration
   - After identity theft, it will always restore to this image

### Current Behavior:

- **On Startup**: Bot detects its current avatar and saves it as "original"
- **During Identity Theft**: Bot steals user avatars temporarily
- **After Identity Theft**: Bot automatically restores to the original pixel art avatar
- **Manual Restore**: Admin can use `!restore` command to force restoration

### Features:

✅ **Auto-Detection**: Bot automatically detects its current avatar as default  
✅ **Rate Limit Handling**: Handles Discord's avatar change limits gracefully  
✅ **Manual Override**: Admin can force restoration with `!restore` command  
✅ **Startup Restoration**: Always restores to original on bot restart  

The pixel art avatar (black masked character with green jacket) will now be the bot's permanent default identity! 