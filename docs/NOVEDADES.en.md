# Changelog

**Last updated:** September 15, 2026

A plain-language summary of Purgito's new features, improvements, and
fixes. The full technical detail, for anyone who wants to read it, lives
in the [GitHub repository](https://github.com/punkyyy01/bot-discord-purg).

# 2026

## Recent updates

### New
- Visible usage limits per server: learned messages, GIFs, and meme images each have a cap, and the dashboard warns when a server is getting close to it.
- **Phrases** category in `/settings`: add, view, and delete special phrases straight from Discord, without opening the dashboard.
- **YouTube** and **Automatic memes** expanded in `/settings`: you can now add subscriptions and turn on automatic memes right from the Discord panel, not just remove them.
- Button to wipe a server's corpus from `/settings`, with a required confirmation before deleting.
- `/mis_datos`: download everything Purgito saved of your writing style as a file.
- `/imitar_mezcla`: blends two members' styles into a single generated message.
- Export and import embed templates as a file, to reuse them across servers.
- Scheduled announcements: weekly mode (pick specific weekdays and a fixed time), in addition to interval or daily.
- Live Twitch alerts: same idea as YouTube notifications, with optional role mentions.
- `!dl <link>` / `purgito dl <link>`: downloads a video from Instagram, TikTok, or Twitter/X and uploads it to the channel.
- Per-server custom text command prefix (it used to be fixed at `!`).
- The dashboard's GIFs tab now shows who sent each GIF, with a view to see just one person's.
- Expanded Stats tab: activity over the last 14 days, who fed the corpus the most, and the most frequent words.

### Improved
- The welcome message no longer mentions memes on non-Premium servers.
- Special phrases and configurable reactions are no longer Premium-only: available on every server.
- When automatic memes can't post (no saved photos, or not enough conversation), Purgito now warns once in the channel instead of silently failing every few minutes.
- CHAT and Channels now warn before you leave if a change is still saving or failed to save, so you don't lose it without noticing.
- The channel matrix (speaks/replies/learns) now shows as readable cards on mobile instead of a cramped table with tiny checkboxes.

### Fixed
- A channel with a lot of history no longer eats into the learned-message quota of other channels on the same server — the limit is now per channel.
- Same fix for `/imitar`: a very active member no longer displaces another member's saved style.
- Videos flagged as sensitive content by Instagram, TikTok, or Twitter can now only be uploaded with `!dl` in a channel marked NSFW.

## Version 1.1.0 — June 28, 2026

### New
- Meme generation with `/momo` and `/meme`, with AI-generated captions and an automatic fallback when there's no connection.
- Image collection for memes: reacting with 🎯 on a photo saves it as a template.
- Schedulable automatic memes per channel.
- Configurable special phrases, with a low chance of appearing and a minimum time between each.
- Configurable automatic reactions to chat messages.
- YouTube notifications when a channel uploads a new video.
- Chat mode: Purgito replies automatically when mentioned or replied to.
- `/imitar @user`: generates a message imitating a specific member's style.
- Welcome message when the bot is added to a new server.
- `/settings` configuration panel, organized by category.
- `/setup`: step-by-step guide to set up a new server.

## Version 1.0.0 — June 1, 2026

### New
- First public release: per-server GIF collection and text generation from what the bot learns in chat.
