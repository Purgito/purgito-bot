# Privacy Policy

**Last updated:** November 7, 2026 (version 2.3)

This Policy explains what personal data Purgito processes, what it uses it for, who it shares it with, how long it keeps it, and how you can exercise your rights. It applies to the Discord bot and to the purgito.app website and dashboard.

The controller of the processing is the owner of Purgito. You can write to contacto@purgito.app or use the Privacy Center: https://purgito.app/privacidad.

# 1. Data we process

The data comes from Discord and from what you do in the dashboard and the Privacy Center.

**Identifiers.** Purgito stores the IDs of users, servers and channels, and the display name of whoever writes, so that the bot works and so that we can handle your requests.

**Messages.** In the channels where an administrator turns learning on, Purgito stores the text of messages together with the ID and display name of their author. It uses them to generate replies and spontaneous messages with Markov chains, a statistical method computed on our own server, and it can imitate the writing style of a member of the server. What is learned in a server is used only in that server. Messages are not sent to third-party artificial intelligence services or used to generate text outside our own server; they reach Cloudflare only inside the encrypted backups (see section 5).

NSFW channels are always excluded from learning; if a channel that was already enabled becomes NSFW, its stored history is deleted immediately. Administrators can also ignore channels and exclude specific people, and if you delete a message on Discord, Purgito removes it from what it has learned.

**GIFs and images.** Purgito stores in Cloudflare R2 the GIFs in each server's gallery and the images used in announcement and embed templates. For each GIF it records who sent it (user, channel and source message) and how many times it was shared; server administrators see this in the dashboard's catalog, with a link to the message and a filter by person. GIFs are not captured from NSFW channels or from channels that `@everyone` cannot see.

**Downloads with `!dl`.** The command downloads the video behind the link you paste and uploads it to the same channel. The file is deleted from the server right away and is neither stored nor uploaded to R2. Whoever uses the command is responsible for having the right to redistribute the video (see the Terms of Service).

**Dashboard.** When you sign in with Discord, we ask for access to your identity, your email and the list of your servers (`identify`, `email` and `guilds`), to show you your profile and only the servers you administer. A session cookie keeps you signed in; it is not used for advertising or tracking. Your Discord email is kept only inside that encrypted cookie, not in our database.

When an administrator changes settings from the dashboard, an audit record is kept with their ID and display name, the action taken and, sometimes, a detail they wrote. Only the administrators of that server can see it, in the History tab. Changes made with `/settings` on Discord are not recorded there.

**Special phrases and boosts.** Special phrases keep the ID and name of whoever added them. Boosts store who boosts, the server and the date, so that we can thank them.

**Payments.** Premium payments are processed by Polar.sh, which acts as Merchant of Record and handles your card and billing details under its own [Privacy Policy](https://polar.sh/legal/privacy). Purgito stores which server has Premium, since when and on which plan, along with the Discord ID of the buyer, Polar's customer and subscription identifiers, their status and dates, and whether a cancellation is scheduled. The buyer can see this at `/perfil/facturacion`; nobody else on the server can. We do not store card numbers, billing details, or the buyer's email or name.

**IP address and technical logs.** purgito.app runs behind Cloudflare, which sees the IP address of visitors. On our server the IP is used only to limit abuse and is not stored in the database. If suspicious activity is detected, the security log stores a code derived from the IP, which makes it possible to recognise a single origin without revealing it. The web server's access logs record the address visited as it arrives (which may include URL parameters) and the browser, but not the IP; we are preparing a change to stop storing those parameters.

**Usage statistics.** To measure how the bot is used and how well it works, the operator uses an internal tool that keeps hourly counts of features, commands and outcomes, without message text, arguments, users or channels. Servers are identified by codes that do not reveal their Discord ID. Only authorised operators have access, and the data is not sent to external analytics services.

We do not ask for your Discord password or store bank card details.

# 2. What we use the data for

We use the data to make the bot work: generating text with Markov chains, maintaining the GIF gallery, running automations and each server's settings, managing Premium, and handling your requests. We do not sell personal data or use it for advertising.

For this, Purgito uses two privileged Discord permissions. Message content lets it learn from enabled channels, trigger text-based responses, detect GIFs and re-read a channel's history when an administrator asks. Server members lets it send welcome and goodbye messages, detect boosts and search for members in the dashboard. Without these permissions, the features that depend on them would stop working.

# 3. Who we share data with

Purgito relies on providers that process data only to the extent needed to deliver their service:

- **Discord**, the platform the bot runs on, which delivers the messages and names Purgito processes.
- **Cloudflare**, which provides the network and protection for purgito.app, handles forwarding of the contact email, and hosts in R2 the GIFs, the images and the encrypted backups.
- **Polar.sh**, which processes Premium payments.
- **Railway**, where Purgito Monitor is hosted: our own monitoring service, which receives status signals and failure alerts without user, server or channel identifiers.
- **Twitch**, only if an administrator sets up live-stream alerts: the bot queries public data and sends no data about the people on the server.

Discord, Cloudflare, Polar.sh and Railway may process data outside Chile, so some information may be processed in other countries. We have not yet assessed the level of data protection in each of them; we limit what we send to each provider to what it needs for its service.

# 4. How long we keep data

Data is kept only as long as it is needed, for these periods:

- **Learned messages, each person's writing style and the record of who sent each GIF:** up to 180 days from when Purgito learned them. Earlier than that, if a server reaches its message limit (higher with Premium), the oldest are discarded. The purge runs daily and also covers inactive servers.
- **GIFs:** if you delete the original message on Discord, the sender record is deleted and, if nobody else shared the GIF independently, so are the GIF and its file. After 180 days that record is deleted as well, but the GIF may stay in the gallery without attribution until an administrator removes it.
- **Audit log and usage statistics:** 90 days.
- **Special phrases and scheduled announcements:** as long as they exist.
- **Technical server logs, including the IP-derived code:** they are rotated when full and today have no fixed period in days; we are preparing an automatic purge after 30 days and will update this Policy when it is active. The web server's access logs, about 14 days.
- **Rights and deletion requests:** 90 days after they are resolved.
- **Data of a server the bot leaves:** kept for 30 days in case the bot is invited again, and deleted afterwards. In the meantime it cannot be managed from the dashboard; if you are an administrator and want it deleted sooner, write to us.

Administrators can also empty the learned messages or delete the stored GIFs at any time with `/settings`.

# 5. Backups and deletion

So that the service can be recovered after a serious failure, a backup of the whole database, including learned messages, is made every day. It is encrypted before leaving the server and stored in a private Cloudflare R2 space and, in addition, on the server itself. It is used only to recover the service and to check that it can be restored, and for nothing else.

Our limit is that none of these backups exceeds 14 days while the service is operating normally. R2 keeps the backups of the last 7 days and those of the Sundays of the last two weeks, and the server keeps the two most recent. An extra backup made for maintenance may be kept a few more days, always within that limit. If the server were switched off or the service interrupted, a backup could exceed that period until the service resumes; it is then deleted with the backups that follow.

Some backups made before November 5, 2026 still exist. They are encrypted with a key that was lost, so they cannot be read or restored, and they are deleted from November 19, 2026.

Backups made before a deletion may still contain that data, encrypted, until they expire. They are neither read nor restored except to recover the service and, if that happened, the deletions already requested are applied again before the service is put back into operation.

For that we keep, for 15 days, a minimal record with no messages or other content: your Discord ID (or the server's) with the dates of the request, and the IDs of deleted messages and channels. We also keep the list of people excluded from learning, until they lift the exclusion. An encrypted copy of this record is also kept in the private R2 space and is deleted after 15 days or, if the service were interrupted, as soon as it resumes.

Deletion is carried out on the live database and on the files in R2 by logical deletion. We cannot guarantee immediate physical destruction of the underlying storage blocks; encryption reduces that risk but does not remove it.

# 6. Your rights and how to exercise them

You can exercise your rights of access, rectification, erasure, objection and portability, and ask for temporary blocking of processing, from the Privacy Center (https://purgito.app/privacidad) by signing in with Discord (the bot has no commands for this). There you can:

- **Download your data** as a JSON file: learned messages by server, GIFs you sent, boosts, special phrases, exclusions and the status of your requests.
- **Request deletion of your data.** The request is recorded immediately and we aim to complete it within 7 calendar days. This is an operational target, not an absolute guarantee: if it fails, is delayed or nears the deadline, the system alerts the controller so they can step in; if the service were interrupted, it is completed as soon as it resumes. You can follow its status on the same page.
- **Exclude yourself from learning and from interaction with Purgito** on every server, including your GIFs and the re-reading of history. The exclusion does not delete what is already stored; deletion does that.
- **Make other requests** (additional access, rectification, objection, portability, temporary blocking or other questions) using the Center's form. We ask only for the type of request, an optional comment and, if you want the answer by email, an address that is deleted once we reply.

Every request gets an immediate acknowledgement of receipt, with a number and a date, and the written answer is available in the Center. We reply within 30 calendar days; the law allows that period to be extended once by up to 30 more days, which we do not plan to do and, if it were necessary, we would tell you before the first period expires. Temporary-blocking requests are answered within 2 days.

If we reject a request, the answer explains why and tells you that you have thirty business days to complain to the Personal Data Protection Agency, which you may also contact if we do not reply on time.

Deletion removes, on every server where you have written, your writing style, the messages Purgito learned from you (including the server's collective copy), your record as a GIF sender (and the GIF and its file, if nobody else shared it independently), your boosts and your rights requests. Your name and ID are removed from special phrases, scheduled announcements and the audit log, which remain as the server's history with your identification replaced by `[eliminado]`. Your original messages on Discord are not affected. The deletion request, with your ID, is kept for 90 days after it is completed so that we can account for it.

If you cannot sign in with Discord, write to contacto@purgito.app; we will ask only for what we need to confirm the account is yours. Server administrators, for their part, can exclude specific people from interaction with the bot, from learning, or from both.

Law No. 21.719 on personal data protection, published on December 13, 2024, enters into force on December 1, 2026; until then Law No. 19.628 applies. We offer these channels from now on.

# 7. Security

We apply reasonable measures to protect the information. The database is not accessible from the Internet, administrative access to the server is restricted and limited to what is needed to run the service, and passwords and tokens are kept outside the database. Backups are encrypted before they leave the server.

The service's data and secrets live on an encrypted volume, which protects against copies of the disk but not against someone with administrative access while the volume is open. No system offers absolute security against incidents or unauthorised access.

# 8. Minors

Purgito is intended for people who meet the minimum age required by Discord. If you are a parent or guardian and believe Purgito holds data about a minor, write to contacto@purgito.app and we will review it.

Purchasing Premium requires legal capacity to enter into a contract or the authorisation of a responsible adult. Purgito does not actively verify this: it is up to the buyer.

# 9. Changes and contact

We may update this Policy to reflect new features, technical changes or legal changes. The date and version always identify the current text, and the history of changes to the code is public on GitHub.

For questions about this Policy or to request deletion of your data, write to contacto@purgito.app or use the Privacy Center. You can also drop by the support server on Discord (https://discord.gg/5U7HKyxnBv), but for matters about your data, use email or the Privacy Center, not the public chat.
