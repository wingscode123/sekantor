# ADR-0012: Telegram pairing, allowlist and redaction

- Status: Superseded by ADR-0021
- Date: 2026-11-11

## Context
PRD Security: Telegram only answers chats registered at pairing; secrets in tool input are masked
before they reach Telegram; approving a risky command needs a second confirmation in the UI and
cannot be done from Telegram.

## Decision
- **Long polling** (`getUpdates`), no webhook: no open port, no tunnel.
- **Pairing**: `ronda pair telegram` asks for the bot token without echoing it, checks it with
  `getMe`, prints a one-time 6-digit code valid for 5 minutes, and registers the chat that sends
  `/pair <code>` to the bot. Token and allowlist live in `~/.ronda/telegram.json`, mode 600.
  `ronda unpair telegram` deletes the file.
- **Allowlist**: updates from any other chat are ignored (and logged without their content).
- **Redaction** (`ronda.relay.redact`): key/token/password assignments and flags, bearer tokens,
  credentials in URLs, and well-known key formats (OpenAI, Anthropic, GitHub, Slack, AWS, Google,
  JWT) are replaced with `<redacted>` in every text sent to Telegram or a webhook.
- **Risky commands**: Telegram shows Deny only, with "approve it on your computer". The hub refuses
  an approve from channel `telegram` for a risky command even with `confirm` (defence in depth).
- Callback data carries a short random key, never a session id or command.

## Consequences
- Messages leave the machine through Telegram's servers: agent names, project names and redacted
  summaries. That is the point of the feature; users who do not want it do not pair.
