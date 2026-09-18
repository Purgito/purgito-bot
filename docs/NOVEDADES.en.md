# Changelog

**Last updated:** September 18, 2026

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
- `!dl <link>` / `purgito dl <link>`: downloads a video from Instagram, TikTok, Twitter/X, or Facebook and uploads it to the channel — also works by replying to a message that has the link, no need to repeat it.
- Image-editing commands (`!deepfry`, `!caption`, `!triggered`, `!wasted`, `!wanted`, and more — full list in `/help`): applied to the image you upload, the one you're replying to, or your avatar if there's neither. Work with `!` or `purgito` in front, same as `!dl`.
- `!gif`: converts a video into a GIF -- attached, or an Instagram/TikTok/Twitter-X/Facebook link (your own or from the message you're replying to), same as `!dl`. `!gifcaption`, `!gifspeed`, `!gifreverse`, and `!gifwide` edit a GIF you already have (add text, change speed, reverse it, stretch it).
- Per-server custom text command prefix (it used to be fixed at `!`).
- The dashboard's GIFs tab now shows who sent each GIF, with a view to see just one person's.
- Expanded Stats tab: activity over the last 14 days, who fed the corpus the most, and the most frequent words.
- Manager role (Server tab → General): delegate a Discord role with access to Announcements, Embeds, Phrases, Triggers, Reactions, GIFs, and YouTube/Twitch/RSS, without giving out Administrator or full "Manage Server".
- Export and import the chat's behavior settings (enabled, frequency, and probabilities) as a file, to reuse it on another server.
- A heads-up in the updates channel when a server is getting close to or hits the cap for saved GIFs or special phrases.
- First steps checklist in INICIO: three steps (choosing learning channels, having something learned already, customizing the style) that check themselves off as they're completed, and the checklist hides itself once they're done.
- Public Changelog page (`/en/changelog`, `/es/novedades`): a plain-language summary of what's changed in Purgito — linked from Resources in the site menu.
- Filter to show only already-configured channels in the channel matrix, on top of searching by name.
- Undo when deleting a phrase, trigger, or reaction: a prompt gives you a few seconds to cancel before it's actually deleted.

### Improved
- The sidebar scrollbar on the Purgito Guide no longer uses the browser's default color.
- The server switcher in the dashboard no longer looks cramped against the sidebar's edge.
- A single module search in the dashboard: there used to be two doing the same thing, and the sidebar one disappeared when you collapsed it.
- More consistent spacing between title, description, and content within the Stats tab.
- The welcome message no longer mentions memes on non-Premium servers.
- Special phrases and configurable reactions are no longer Premium-only: available on every server.
- When automatic memes can't post (no saved photos, or not enough conversation), Purgito now warns once in the channel instead of silently failing every few minutes.
- CHAT and Channels now warn before you leave if a change is still saving or failed to save, so you don't lose it without noticing.
- The channel matrix (speaks/replies/learns) now shows as readable cards on mobile instead of a cramped table with tiny checkboxes.
- The First steps guide in INICIO can be dismissed even with steps left unfinished, and the step about learning new messages no longer reads like a repeat of choosing channels.
- Fewer redundant dashboard modules: Customization is now edited directly from INICIO (it used to lead to a separate page with the same thing), and Command prefix + Memory cleanup were merged into one module, General. The bot's updates channel setting moved to Automation, alongside YouTube/Twitch/RSS.
- The dashboard's sidebar now starts with its categories collapsed (only the one for the module you're viewing opens), so it no longer has its own scroll separate from the rest of the page.
- `/refeed_channels` now has a 60-second per-server cooldown, so it can't be accidentally relaunched several times in a row.
- HISTORIAL's action filter now has specific options for more change types (user exclusions, command prefix, Twitch, mention channels, updates channel, phrases), instead of lumping them all under "All actions".
- The dashboard now loads faster, especially the first time you open it in a session.

### Fixed
- The dashboard's YouTube module showed an error ("emptyState is not defined") instead of the subscription list.
- Stats showed every text channel as "read" even when only a few were actually enabled to learn from.
- In Automatic reactions, adding an emoji closed the modal (you had to reopen it for each one) and adding several in a row often got blocked for too many requests.
- A channel with a lot of history no longer eats into the learned-message quota of other channels on the same server — the limit is now per channel.
- Same fix for `/imitar`: a very active member no longer displaces another member's saved style.
- Videos flagged as sensitive content by Instagram, TikTok, or Twitter can now only be uploaded with `!dl` in a channel marked NSFW.
- The "Choose which channels it learns from" step in INICIO's First steps guide now correctly unchecks itself if you remove all learning channels — it used to stay marked as done forever.
- Adding a special phrase identical to one that already exists in the same pool is now rejected instead of saving a duplicate.
- A new GIF with a thumbnail similar to another server's no longer gets mistaken for that server's content.
- `!dl` and `!gif` find the video when replying to another bot's message, whether it shows it as a link preview, a file attachment, or a video embedded in the message (e.g. another meme bot's result) — `!gif` used to ask for a video anyway, even when it looked perfectly fine in Discord.

## Version 1.1.0 — June 28, 2026

### New
- Meme generation with `/momo` and `/meme`, with AI-generated captions.
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
