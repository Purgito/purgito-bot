# Privacy Policy

**Last updated:** November 6, 2026

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

Channels marked **NSFW** in Discord are always excluded from this learning: Purgito never stores messages from an NSFW channel, with no exception and no way to manually enable it for the corpus. If a channel that was already enabled for the corpus gets marked NSFW later, the history already saved from that channel is purged immediately.

---

## Media

The bot may store:

- Image URLs.
- GIF URLs.
- Media files needed for the GIF gallery and announcement/embed template features.

Where applicable, these files may be stored persistently via Cloudflare R2.

For every GIF saved to the gallery, the bot also records who sent it: user ID, channel, and source message, plus how many times they shared it (including re-sharing a GIF someone else already saved). The GIF catalog in the admin panel, visible to the server's admins, shows this data with a direct link to the original message and a filter to see one person's GIFs.

---

## Display name

A user's Display Name may be stored alongside certain messages to enable features like user impersonation.

---

## Server boosts

To thank a boost and avoid repeating the notice, Purgito stores the ID of the person boosting a server, the server ID and the date since which they boost. It is used only for that feature, it is included in the download of your data and it is deleted when you request deletion.

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

When a person requests deletion of their data (from the Privacy Center), this log is **not deleted**, because it is the server's history: only who did it is removed. Their ID and name are replaced with `[eliminado]` in the entries where they acted, and their ID disappears from the detail of entries that mention them. The same applies to the special phrases and scheduled announcements they created: they stay on the server, without their name. Their data copy includes these entries, with other people's identifiers hidden.

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

## Aggregate product analytics (optional)

The operator may enable Purgito Studio to measure bot usage and quality. This
module stores hourly counts by feature, registered command, outcome and version,
installation inventories and observed membership changes. Server HMAC keys allow
community-level counts and cohorts without exposing Discord server IDs in the
panel. These are pseudonyms, not identifiers of people. Studio does not collect
message text, command arguments, user IDs or channel IDs.

New Studio data stays in the bot's PostgreSQL database and is not sent to external
analytics services. Only authorized operators can access the private panel.
Retention defaults to 90 days (configurable from 7 to 365), with daily cleanup
while the collector is enabled; backups follow their own retention policy. These
conditions apply to Studio; other bot features and integrations remain covered
by the preceding sections.

---

# 2. Use of information

The information collected is used exclusively to provide the bot's features, including:

- Text generation via local Markov chains.
- GIF gallery.
- Server automations.
- Command and preference configuration.

Data is **never sold**, nor used by Purgito for advertising.

---

## Learning from messages (Markov chains)

Purgito generates text with **Markov chains**, a simple statistical method (word sequences) computed on Purgito's own server over a sample of the messages learned **from each server separately**. It does not use third-party artificial intelligence services and does not send message content to any third party to generate text (the Groq integration and automatic memes were retired). Models are rebuilt in memory from what is stored and are discarded when the data is deleted. If you do not want Purgito to learn from your messages, you can opt out from the Privacy Center.

## Discord privileged permissions used by Purgito

- **Message Content:** needed to learn from messages in enabled channels (corpus and writing style for imitation), to fire text *triggers*, to detect shared GIFs and to re-read a channel's history when an administrator asks for it. NSFW channels and channels that `@everyone` cannot view are left out of GIF capture; NSFW channels are also left out of learning.
- **Server Members:** needed for welcome and goodbye messages, to detect a new server boost and to search members in the admin panel.

If Discord did not grant any of these permissions, the features that depend on it would become unavailable.

---

# 3. Third-party services

Purgito uses external services for certain features. Each provider processes only the information necessary to provide its service.

## Discord and storage

- **Discord**: For platform communication, receiving events, authentication, and sending messages.
- **Cloudflare R2**: For persistent storage of media files (GIFs uploaded to the gallery and images uploaded from the embed editor) and, in a separate private space, the encrypted backups described in section 4.

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

On top of the quota there is a **hard limit of 180 days**: learned messages (the server corpus, each person's saved style for `/imitar`, and the record of who sent each GIF) are deleted automatically once 180 days have passed since Purgito learned them, even if the quota was not reached. The purge runs daily, does not depend on any admin, and also applies to inactive servers. The limit is chosen so it does not hurt how the bot works: Purgito generates text from a random sample of at most 5,000 messages of the server (2,000 per person), so an active server replaces that material long before six months pass, and an inactive one only loses what no longer reflects how it talks.

Server admins can also delete collected content at any time using the interactive settings panel (`/settings` command), which includes buttons to clear the learned message corpus and to delete saved GIFs.

**GIFs** saved in the gallery are linked to who sent them (user, server, channel and message) so they can be removed. If you delete the message in Discord, that record is deleted and, if nobody else shared that same GIF independently, the GIF is removed from the collection and its file is deleted from our storage (Cloudflare R2). If other people shared it, the file is kept as long as any independent reference exists. After 180 days the record of who sent it is deleted; the GIF may remain in the server's gallery without that attribution until an administrator removes it.

The panel's audit log (see section 1) is kept for a maximum of 90 days from each entry and then purged automatically, with no manual intervention.

When the bot leaves a server (for example, if it's kicked), that server's data is kept for a 30-day grace period before being deleted from the live database (backups expire separately, see below). This is so that, if the bot is re-invited within that window, the server gets its configuration and content back without having to be set up again from the beginning. During that period, while the bot isn't in the server, it isn't possible to access the admin panel to manage that data. There's currently no self-service way to speed up this deletion at the server level before the 30 days are up; if you're a server admin and want its data deleted sooner, you can request it by contacting the developer (see "Contact" below).

---

## Where data is stored, and backups

All the information Purgito stores (each server's settings, learned messages, audit log, etc.) lives in a PostgreSQL database on the server where the bot runs. The database only accepts connections from that same server; it is not exposed to the Internet. The database data and the service secrets are stored on an encrypted volume (LUKS2). Images and GIFs live in Cloudflare R2.

To be able to recover the service after a serious failure, a backup of the whole database is made every day. That backup contains the same as the live database, including the messages Purgito learned. It is encrypted with age before leaving the server and stored in a private Cloudflare R2 space (no public access), plus an encrypted copy on the server itself. **R2 keeps the backups of the last 7 days and those of the last 2 Sundays; the server keeps only the 2 most recent. No backup reaches 14 days: each one is deleted automatically before then.** There are no other copies of the database with longer retention: Purgito's disk is excluded from the host machine's automatic backups. To check that a backup can be restored, the project owner downloads it to their own machine, restores it into an isolated database and deletes it afterwards. They are used only to recover the service after a disaster and for that check; they are not consulted or used for learning or any other function.

---

## Privacy Center: manage your data

All management of your personal data is done at **https://purgito.app/privacidad**, signing in with Discord. There are no Discord commands for this. Purgito only acts on the person who signed in: identity comes from the session, never from data sent by the browser. From there you can:

- **Download your data:** a JSON file with your learned messages by server, the GIFs you sent, your boosts, special phrases in your name, your exclusions and the status of your requests.
- **Request deletion of your data.** The request is registered immediately and completed within a maximum of **7 calendar days**; if an attempt fails it is retried until completed, and you can check its status on the same page.
- **Turn the global exclusion on or off:** from then on Purgito stops learning from your messages and interacting with you on **all** servers (it also does not store your GIFs, nor when re-reading history). The exclusion does not delete what was already stored; deletion does that.
- **Make other rights requests** (access to the information we hold about you beyond the download, rectification, objection, portability, restriction of processing or any other question) with the form in the same Center. We ask only for the type of request and an optional short comment, and answer within a maximum of **30 calendar days**.
- If you **cannot sign in with Discord**, write to contacto@purgito.app; we will ask only for what is needed to verify the account is yours.

**What the deletion request removes**, from the live database and across **all** servers where you have written: your saved writing style for the imitation feature; the messages Purgito learned from you (including the server's collective copy, which carries its author's ID); your record as a GIF sender and, if nobody else shared that GIF independently, the GIF and its file in R2; your boosts; and your rights requests. Your name and ID are removed from special phrases, scheduled announcements and the panel audit log (see section 1), which are kept because they are the server's history. Your original Discord messages are not affected: this only deletes what Purgito stored.

The request, with your ID, is kept for 90 days after completion so we can account for it and is then deleted. The verifiable log of its steps contains neither your identifier nor content.

**The real limit of deletion: backups.** Backups made before your deletion may still contain that data, encrypted, until they expire (at most 14 days, see above). They are not read or restored unless the service has to be recovered after a disaster; if that happened, the deletion is re-applied before the bot is put back into operation. To do that, a **tombstone** is stored: only your Discord user ID and two dates (when you requested deletion and when the tombstone expires), with no content or servers. The tombstone lasts 15 days (the 14 of the backups plus one of margin) and deletes itself. The same happens when Purgito leaves a server and, after the 30-day grace period, deletes all its data: the server ID and two dates are kept for 15 days. So that this record is not lost if the server is lost, every 5 minutes an encrypted copy with those current tombstones and the list of people excluded from learning (IDs and dates, no messages) is stored in the same private R2 space; each copy is deleted after 15 days at most, and an exclusion is kept as long as the person does not remove it.

The same applies to messages you delete in Discord and to channels that are deleted or become NSFW: Purgito removes them from what it learned (including associated GIFs) and, if a backup ever had to be restored, that removal is re-applied (only the message identifier, with no content, is kept for 15 days).

**What we do not promise.** Deletion works on the live database and on the files in R2 by logical deletion; we cannot guarantee immediate physical destruction of blocks in the underlying storage. Encryption of volumes and backups reduces that risk but does not eliminate it.

---

# 5. User rights

You can exercise your rights over your personal data —access, rectification, deletion, objection and portability, and ask for restriction of processing— from the Privacy Center (**https://purgito.app/privacidad**) or, if you cannot sign in with Discord, by writing to contacto@purgito.app (see section 4). Chile's Law No. 21.719 on personal data protection recognizes rights for data subjects; Purgito offers these channels to exercise them. This policy describes current practices and is not legal advice.

Server administrators also have their own tools to control data collection for their community (see section 4), including the ability to exclude specific users: independently, they can mark that Purgito should not interact with that user (not reply, react or fire triggers) and/or not learn from their messages (not use them for the corpus or the imitation feature).

# 6. Minors

Purgito is intended for users who meet Discord's minimum age requirements.

Purchasing Premium requires having the legal capacity to enter into a contract, or the authorization of a responsible adult. Purgito doesn't actively verify this; it's the buyer's responsibility.

---

# 7. Security

Reasonable measures are taken to protect stored information: the database isn't reachable from the Internet, administrative access to the server is restricted, backups are encrypted before leaving the server, and passwords and tokens are kept outside the database.

The volume holding the database and the secrets is encrypted at rest (LUKS2), which protects copies of the disk; it does not protect against someone with administrative access to the server while the volume is open. Access to people's data is limited to operating the service. No system can guarantee absolute security against incidents or unauthorized access.

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
