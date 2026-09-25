# Privacy Policy

**Last updated:** September 21, 2026

This Policy describes how **Purgito** collects, uses, stores, shares, and protects the information it needs to provide its features.

Purgito is a public Discord bot used by multiple servers. The data we collect and how we handle it are the same for every server where the bot is present.

---

# 1. Information collected

To work correctly, the bot may store the following information:

## Discord information

- User IDs.
- Server IDs.
- Channel IDs.

These identifiers are used solely for the bot's internal operation.

---

## Message content

When the learning features are enabled, the bot stores the content of text messages sent in allowed channels.

These messages may be used to:

- Train local Markov chains.
- Generate automatic chat replies.
- Mimic users' writing style.
- Serve as a limited vocabulary sample in meme generation (locally with Markov, or through the optional Groq integration if configured).

Channels marked **NSFW** in Discord are always excluded from this learning: Purgito never stores messages from an NSFW channel, with no exception and no way to manually enable it for the corpus. If a channel that was already enabled for the corpus gets marked NSFW later, the history already saved from that channel is purged immediately.

---

## Media

The bot may store:

- Image URLs.
- GIF URLs.
- Media files needed for the GIF gallery, meme collection, and announcement/embed template features.

Where applicable, these files may be stored persistently via Cloudflare R2.

For every GIF saved to the gallery, the bot also records who sent it: user ID, channel, and source message, plus how many times they shared it (including re-sharing a GIF someone else already saved). The GIF catalog in the admin panel, visible to the server's admins, shows this data with a direct link to the original message and a filter to see one person's GIFs.

---

## Display name

A user's Display Name may be stored alongside certain messages to enable features like user impersonation.

---

## Special phrases

When an admin adds a special phrase from the panel (Chat tab → Phrases), Purgito stores the Discord ID and display name of whoever added it, along with the phrase's text. Unlike the audit log (see below), this attribution has no expiration date: it's kept for as long as the phrase exists.

---

## Logging in to the web panel

When you log in to purgito.app with Discord, the `identify`, `email`, and `guilds` scopes are requested. This lets us show your username, avatar, and email within your own session, and link your Discord account to the servers you manage (the `guilds` scope is what lets us know which servers you have admin permissions on, so we only show you those in your dashboard). A session cookie is stored to keep you logged in while you browse the site; this cookie isn't used for advertising or cross-site tracking.

---

## Panel audit log

When an admin makes a configuration change from the web dashboard (purgito.app), Purgito stores an audit log specific to that server: the Discord ID and display name of whoever made the change, what type of action it was (for example, adding a special phrase, adding a GIF, or removing a channel from the learning channels), and, in some cases, a free-text detail that may include content written literally by whoever made the change.

This log covers changes made from the web dashboard. Actions an admin runs directly from the `/settings` command in Discord — including the buttons to wipe the entire corpus or delete all saved GIFs (see "Data retention") — take effect immediately but aren't recorded in this log.

This log is visible only to that same server's admins, in the panel's History tab, and exists so the community can see what changes were made and by whom. It's kept for a maximum of 90 days and then deleted automatically (see "Data retention").

---

The bot **does not collect**:

- Passwords.
- Email addresses, except the one Discord provides when logging in to the web panel (purgito.app) — that email is used only to identify you within your own session and isn't shared with third parties.
- Personal data other than what's provided by Discord's official API.

**IP addresses:** the dashboard (purgito.app) processes your IP address transiently and narrowly, solely to prevent abuse (request rate limits). That IP lives only in the process's memory for a short window (seconds to minutes), is never saved to the database or to any persistent log, and isn't shared with third parties.

For payment data, see the **"Payments and subscriptions"** section below.

---

## Payments and subscriptions

When a server purchases Premium through the dashboard (purgito.app), the payment is processed by **Polar.sh**, not Purgito.

**Purgito stores:**

- The ID of the server (guild_id) with active Premium, the date it was activated, and a text note identifying the plan (for example, "Polar — monthly" or "Polar — annual").
- The Discord ID of whoever started the purchase, along with internal identifiers for the Polar subscription (customer and subscription IDs) and its status (active, trialing, canceled), its period and trial dates, and whether it has a scheduled cancellation. This lets whoever paid see their own subscription's status at `/perfil/facturacion` — no one else on the server can see this information.

Purgito **does not store** the card number, billing details, or the buyer's email or name.

**Polar.sh does collect** the data needed to process the payment (card, email, billing details) under its own [Privacy Policy](https://polar.sh/legal/privacy). That relationship is between the buyer and Polar.sh, in its capacity as payment processor and Merchant of Record.

---

# 2. Use of information

The information collected is used exclusively to provide the bot's features, including:

- Text generation via local Markov chains.
- Meme and caption generation (locally, or through the optional Groq integration).
- GIF gallery.
- Server automations.
- Command and preference configuration.

Data is **never sold**, nor used by Purgito for advertising.

---

# 3. Third-party services

Purgito uses external services for certain features. Each provider processes only the information necessary to provide its service.

## Discord and storage

- **Discord**: For platform communication, receiving events, authentication, and sending messages.
- **Cloudflare R2**: For persistent storage of media files (images in the server's meme pool and GIFs uploaded to the gallery).

## Groq API (AI meme captions)

- **What it is and what it's used for**: Groq is an external AI model inference provider (vision and language) used optionally and exclusively to analyze images and write captions in the meme feature.
- **What data may be sent**: The image used for the meme (base64-encoded) and a limited sample of the server's corpus (up to a maximum of 25 short messages and 15 long messages, as a reference for vocabulary and tone).
- **When it's used**: Only when a meme is requested or generated (`/momo` command, image-trigger reply, or scheduled meme), and only when the `GROQ_API_KEY` has been configured by the bot's operator.
- **Narrow scope**: Groq doesn't process regular chat conversations and doesn't receive any server's full corpus. Purgito's general conversation runs entirely locally.
- **Local fallback**: If Groq isn't configured, unavailable, or fails, caption generation happens entirely locally via Markov chains.
- **Advertising**: Data sent to Groq for this feature isn't used by Purgito for advertising or data sale.

## Twitch API (live stream notifications)

- **What it is and what it's used for**: Twitch is the streaming platform whose API is queried, optionally, to post in a Discord channel when a Twitch channel an admin configured goes live.
- **What's sent**: No information about the server's users. The bot uses its own application credentials (not any Discord user's) to query public Twitch data, such as whether a channel is live and the stream title.
- **When it's used**: Only if the bot's operator configured `TWITCH_CLIENT_ID`/`TWITCH_CLIENT_SECRET`; otherwise the feature stays disabled.

## Social media video download (`!dl`)

- **What it is and what it's used for**: The `!dl` command downloads a public video from Instagram, TikTok, Twitter/X, or Facebook from a link a user pastes, and uploads it to the same Discord channel.
- **What's processed**: Only the pasted URL and the video downloaded from it. The file is saved to a temporary process directory and deleted immediately after being sent to the channel — it isn't stored persistently or uploaded to Cloudflare R2.
- **Responsibility**: Purgito doesn't verify whether whoever pastes the link has the right to redistribute that content (see "Redistributed third-party content" in the Terms of Service).

## Payments and infrastructure

- **Polar.sh**: Payment processor and Merchant of Record for Premium subscriptions. See its [Privacy Policy](https://polar.sh/legal/privacy).
- Other infrastructure services strictly necessary for the bot to operate.

---

# 4. Data retention

Collected data is kept only for as long as it's needed for the bot to function.

Message history isn't kept indefinitely, even while a server stays active: each server has a maximum quota of stored messages (higher on Premium servers). Once that quota is reached, the oldest messages are discarded automatically as new ones are saved, with no admin needing to do it manually.

Server admins can also delete collected content at any time using the interactive settings panel (`/settings` command), which includes buttons to clear the learned message corpus and to delete saved GIFs.

The panel's audit log (see section 1) is kept for a maximum of 90 days from each entry and then purged automatically, with no manual intervention.

When the bot leaves a server (for example, if it's kicked), that server's data is kept for a 30-day grace period before being deleted entirely. This is so that, if the bot is re-invited within that window, the server gets its configuration and content back without having to be set up again from the beginning. During that period, while the bot isn't in the server, it isn't possible to access the admin panel to manage that data. There's currently no self-service way to speed up this deletion at the server level before the 30 days are up; if you're a server admin and want its data deleted sooner, you can request it by contacting the developer (see "Contact" below).

---

## Deleting your own data (individual right to be forgotten)

Regardless of the above, any user can request at any time that their own information be deleted, without needing to be a server admin or wait for the 30-day period above.

The `/borrar_mis_datos` command, available to anyone on any server where Purgito is present, permanently and immediately deletes, across **every** server where you've written:

- Your writing style saved for the impersonation feature (`/imitar`).
- The messages Purgito learned from you to generate text.

Your original Discord messages aren't affected: this only deletes the copy Purgito saved to learn your writing style. Since this is irreversible, the command asks for explicit confirmation before running the deletion.

This deletion is specifically for the message-learning data described above, and doesn't automatically cover other categories you may have generated on a server — for example, GIFs or images you contributed to the server's pool, your entry as a sender in the GIF catalog, or your own entries in the panel's audit log if you're an admin — since those are tied to the server where they were generated, not just to your account. If you want to request deletion of any of those, you can contact the developer (see "Contact").

---

## Downloading your own data (portability)

Any user can also request a copy of their own information with the `/mis_datos` command, available on any server where Purgito is present. It generates a JSON file with your saved writing style and the messages Purgito learned from you, grouped by server, and sends it to you privately. It's the read-only counterpart to `/borrar_mis_datos`: it doesn't delete anything.

---

# 5. User rights

Any user can delete their own information at any time using the `/borrar_mis_datos` command, and download a copy with `/mis_datos` (see section 4) — both without needing to be a server admin.

Server admins also have their own tools to control data collection for their community (see section 4), including the ability to exclude specific users: independently, they can mark that Purgito shouldn't interact with a user (no replies, reactions, or triggers) and/or shouldn't learn from their messages (not used for the corpus or the impersonation feature).

If you believe there's information that should be deleted and isn't covered by these self-service tools, or you have questions about how data is handled, you can contact the developer.

Where technically possible, reasonable deletion requests will be honored.

---

# 6. Minors

Purgito is intended for users who meet Discord's minimum age requirements.

Purchasing Premium requires having the legal capacity to enter into a contract, or the authorization of a responsible adult. Purgito doesn't actively verify this; it's the buyer's responsibility.

---

# 7. Security

Reasonable measures are taken to protect stored information.

That said, no system can guarantee absolute security against incidents or unauthorized access.

---

# 8. Changes to this Policy

This Policy may be updated to reflect new features, technical improvements, or legal changes.

The "Last updated" date will always indicate the current version.

Purgito's code is hosted on GitHub, where a public version history is maintained.

---

# 9. Contact

If you have questions about this Policy or want to request deletion of information related to the bot, you can contact the developer through:

- Email: contacto@purgito.app.
- The project's official Discord server (when available).
