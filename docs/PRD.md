> Superseded by docs/superpowers/specs/2026-11-16-sekantor-design.md

# Ronda — PRD v1.0

Nov 10, 2026 · @IT New Tech

## Ringkasan & branding

Ronda adalah satu inbox lokal untuk semua AI agent yang berjalan di device kamu (Claude Code, Orca, OpenBot, dan CLI agent lain): lihat siapa yang sedang menunggu, lalu approve atau balas langsung dari satu tempat.

**Nama: Ronda.** Diambil dari *ronda malam*: warga bergiliran menjaga kampung saat yang lain tidur, lalu memukul kentongan kalau ada yang perlu perhatian. Metafora ini pas: agent bekerja berjam-jam, Ronda yang berjaga, dan kamu hanya dipanggil kalau perlu. Namanya pendek, mudah diucapkan secara global, dan membawa cerita asal Indonesia yang membedakan dari puluhan proyek bernama "agent-monitor".

- **Tagline (EN):** Your agents work all night. Ronda keeps watch.
- **Tagline (ID):** Agen kerja, Ronda jaga.
- **One-liner repo:** One inbox for every AI coding agent on your machine. See who's waiting, approve, and reply from one place.
- **CLI:** `ronda` (contoh: `ronda up`, `ronda status`, `ronda reply <id> "..."`)
- **Nama fitur:** notifikasi = *Kentongan*; adapter = *Pos* (pos ronda per platform); daemon = *Warga*. Istilah ini dipakai di dokumentasi sebagai flavor, sedangkan UI tetap memakai label bahasa Inggris yang jelas.

**Identitas visual**

| Elemen | Arahan |
| --- | --- |
| Logo | Kentongan bambu yang disederhanakan: kapsul vertikal dengan satu celah horizontal. Bentuknya sekaligus terbaca sebagai badge notifikasi. |
| Warna utama | Malam `#14162B` (latar), Lentera `#F2A93B` (aksen, status *needs you*), Bambu `#C9B27C` (sekunder) |
| Warna status | Hijau `#3FB37F` running, Lentera `#F2A93B` waiting, Merah `#E5484D` error, Abu `#8B8FA3` idle/done |
| Tipografi | Inter untuk UI, JetBrains Mono untuk event/log |
| Gaya | Minimal, dark-first, padat informasi: terasa seperti tool terminal, bukan SaaS marketing |
| Suara | Tenang dan singkat. Ronda hanya bicara kalau ada yang perlu kamu lakukan. |

Ketersediaan nama sudah dicek sekilas: "Mandor" dan "Ground Control" sudah dipakai proyek lain di ruang yang sama, sedangkan "Ronda" belum ditemukan. Sebelum dikunci, cek dulu org GitHub, npm/PyPI `ronda`, dan domain.

## Problem & target user

Developer yang menjalankan beberapa agent paralel di beberapa aplikasi kehilangan waktu terbesar karena agent diam menunggu input tanpa ada yang tahu. Penyebabnya bukan agent yang lambat.

- Tiap platform (Claude Code desktop, Orca, OpenBot, terminal) punya notifikasi dan UI sendiri, jadi user harus berpindah aplikasi untuk mengecek satu per satu.
- Agent yang menunggu approval atau jawaban bisa diam berjam-jam, misalnya saat user meeting, tidur, atau fokus di agent lain.
- Tool monitoring yang ada umumnya terkunci ke satu agent (kebanyakan hanya Claude Code), atau hanya mengamati tanpa bisa membalas.

**Target user v1.0**

| Persona | Konteks | Kebutuhan utama |
| --- | --- | --- |
| Power user multi-agent | 3–10 agent paralel di 2+ aplikasi pada satu laptop/workstation | Tahu agent mana yang blocked dalam 1 detik, lalu membalas tanpa pindah aplikasi |
| Developer mobile-away | Agent jalan lama saat user meninggalkan meja | Notifikasi ke HP dan approve/reply dari HP |
| Tim kecil / lead (pasca-v1) | Beberapa developer dan mesin | Ringkasan lintas mesin (di luar scope v1.0) |

## Goals & non-goals

v1.0 berhasil kalau user bisa menutup semua jendela agent dan tetap tidak melewatkan satu pun agent yang menunggu.

**Goals v1.0**

1. **Discover:** otomatis mendeteksi sesi agent aktif dari minimal 3 sumber: Claude Code (CLI dan desktop), Orca, dan CLI agent generik di tmux.
2. **Inbox:** satu tampilan yang mengurutkan agent berdasarkan "butuh saya" (waiting approval/input), bukan berdasarkan waktu.
3. **Act:** approve/deny tool call dan membalas teks bebas dari Ronda untuk sumber yang mendukung (Claude Code via hooks, CLI generik via tmux).
4. **Notify:** push notifikasi Kentongan ke desktop dan Telegram saat agent berpindah ke status waiting/error/done.
5. **Local-first:** satu perintah install, semua data tetap di mesin user, tanpa akun dan tanpa cloud.

**Non-goals v1.0**

- Menjalankan atau mengorkestrasi agent. Ronda bukan IDE dan bukan pengganti Orca; Ronda hanya mengamati dan membalas.
- Multi-mesin dan multi-user (direncanakan v1.x).
- Analitik token/biaya, replay sesi, dan review diff.
- Membaca isi layar aplikasi GUI via screen scraping/computer use.
- Aplikasi mobile native. Di v1.0, HP cukup lewat Telegram dan web UI responsif.

## Lanskap kompetitor & positioning

Ruang ini sudah ramai, jadi Ronda hanya layak jika menang di dua hal sekaligus: **lintas platform** dan **bisa membalas**. Kebanyakan tool hanya punya salah satunya.

| Proyek | Cakupan agent | Bisa membalas/approve? | Catatan |
| --- | --- | --- | --- |
| [Riva](https://pypi.org/project/riva/) | 15+ framework (Claude Code, Cursor, Codex CLI, Gemini CLI, ...) | Tidak, hanya observasi | Kompetitor terdekat untuk discovery; secara eksplisit tidak mengeksekusi aksi agent |
| [steerd](https://pypi.org/project/steerd/) | Claude Code | Ya, approve/reject via HP | Relay `PreToolUse` saja, hanya satu agent |
| [AethelHook](https://www.producthunt.com/posts/1245551) | Coding agent | Ya, approve/deny via HP | Fokus remote approval |
| [Pulse for Claude Code](https://www.everydev.ai/tools/pulse-for-claude-code) | Claude Code | Ya, approve tool call via HP | Plus token usage dan search |
| [Claude Code Agent Monitor](https://www.sourcepulse.org/projects/29195119) | Claude Code | Tidak | Dashboard observability via hooks |
| [CloudCLI / Claude Code UI](https://pinggy.io/blog/remotely_manage_claude_code_from_phone/) | Claude Code, Cursor CLI, Codex | Ya, chat penuh | Web UI pengganti terminal, bukan agregator lintas aplikasi |
| [AgentsRoom](https://agentsroom.dev/claude-code-hooks) | Claude Code + CLI lain | Sebagian | Command center sekaligus runner agent |
| [Orca](https://onorca.dev/docs) (built-in) | Agent di dalam Orca | Di dalam Orca | Notifikasi hanya untuk sesi yang dijalankan di Orca |

**Positioning:** *Ronda tidak menjalankan agent kamu. Ronda menjaga semuanya, di mana pun agent itu berjalan.* Ronda adalah lapisan di atas Orca, OpenBot, Claude Code desktop, dan terminal biasa, bukan pengganti salah satunya.

**Diferensiasi v1.0**

- Adapter plugin (*Pos*) dengan kontrak terbuka, sehingga komunitas bisa menambah platform baru tanpa menyentuh core.
- Inbox "needs you" lintas platform, bukan sekadar daftar sesi.
- Kemampuan **reply teks**, bukan hanya approve/deny, untuk Claude Code dan agent apa pun di tmux.
- Telegram sebagai remote control tanpa membuka port.

Sumber diakses 10 Nov 2026.

## User stories

| ID | Sebagai user, saya ingin... | Supaya... | Prioritas |
| --- | --- | --- | --- |
| US-01 | membuka satu halaman dan melihat semua agent aktif dari semua aplikasi | tidak perlu cek tiap aplikasi | P0 |
| US-02 | agent yang menunggu saya selalu ada di paling atas | tahu dalam 1 detik apa yang harus saya kerjakan | P0 |
| US-03 | approve/deny tool call Claude Code dari Ronda | agent tidak berhenti saat saya di aplikasi lain | P0 |
| US-04 | membalas teks ke agent yang selesai/menunggu input | bisa memberi instruksi lanjutan tanpa membuka aplikasinya | P0 |
| US-05 | mendapat notifikasi desktop saat status agent berubah ke waiting/error/done | tidak perlu terus memantau | P0 |
| US-06 | menerima notifikasi di Telegram dan membalas/approve dari sana | bisa mengurus agent dari HP | P1 |
| US-07 | melihat ringkasan pesan terakhir dan konteks (project, branch, tool yang diminta) | bisa memutuskan tanpa membuka sesi | P0 |
| US-08 | klik "Open in source" untuk lompat ke aplikasi asli | bisa masuk lebih dalam kalau perlu | P1 |
| US-09 | membungkam (snooze) agent tertentu | agent yang tidak penting tidak terus menarik perhatian | P2 |
| US-10 | menulis adapter untuk platform baru dalam < 200 baris | komunitas bisa menambah dukungan sendiri | P1 |

## Functional requirements v1.0

Requirement dikelompokkan per modul. P0 wajib untuk rilis 1.0; P1 boleh menyusul di 1.0.x.

**Daemon & discovery**

| ID | Requirement | Prio |
| --- | --- | --- |
| FR-01 | `ronda up` menjalankan daemon lokal (hub + web UI) di `127.0.0.1:7878` | P0 |
| FR-02 | `ronda install claude` memasang hooks Ronda ke `~/.claude/settings.json` dengan backup otomatis, plus `ronda uninstall claude` untuk rollback bersih | P0 |
| FR-03 | Sesi Claude Code (CLI dan desktop) muncul otomatis saat event pertama diterima | P0 |
| FR-04 | Pos tmux memindai semua pane tiap 2 detik dan mengenali CLI agent (claude, codex, opencode, gemini, aider) dari nama proses | P0 |
| FR-05 | Pos Orca membaca sesi lewat Orca CLI/notifikasi; jika tidak tersedia, fallback ke pos tmux/proses | P1 |
| FR-06 | Pos OpenBot via API lokalnya (setelah divalidasi, lihat Open questions) | P1 |
| FR-07 | Sesi yang tidak mengirim event > 10 menit dan prosesnya hilang ditandai `ended` | P0 |
| FR-08 | Host fingerprint: setiap proses agent dilabeli platform asalnya (Orca, OpenBot, VS Code, Cursor, Claude desktop, tmux, terminal biasa) dari process tree, env var (TERM\_PROGRAM, TMUX, WT\_SESSION, VSCODE\_PID, dll.), cwd, dan command line. Script hook Claude Code ikut mengirim parent chain dan env yang sama. | P0 |
| FR-09 | Rule fingerprint disimpan di YAML (pola nama induk, env var, pola path) dan bisa ditambah komunitas; hasilnya punya skor confidence dan sinyal penentunya ditampilkan di UI. Agent yang terdeteksi tapi tidak bisa dibalas tetap muncul dengan label host dan tombol "Open in \<host>". | P1 |

**Inbox & UI**

| ID | Requirement | Prio |
| --- | --- | --- |
| FR-10 | Inbox mengurutkan: `waiting_approval` > `waiting_input` > `error` > `running` > `done`, lalu berdasarkan lama menunggu | P0 |
| FR-11 | Kartu agent menampilkan: sumber, project/cwd, branch, status, lama di status itu, pesan terakhir (≤ 3 baris), tool/command yang diminta | P0 |
| FR-12 | Update real-time via WebSocket, < 1 detik dari event ke UI | P0 |
| FR-13 | Detail sesi: 50 event terakhir dalam timeline | P1 |
| FR-14 | Tombol "Open in source" (deep link Orca/VS Code, atau `tmux select-pane`) | P1 |
| FR-15 | Snooze/mute per agent | P2 |

**Aksi (reply & approve)**

| ID | Requirement | Prio |
| --- | --- | --- |
| FR-20 | Approve/Deny untuk `waiting_approval` Claude Code: hook `PreToolUse` long-poll ke hub dan mengembalikan keputusan | P0 |
| FR-21 | Timeout approval yang bisa dikonfigurasi (default 0 = fallback langsung ke prompt asli di terminal) supaya Ronda tidak pernah membuat agent hang | P0 |
| FR-22 | Reply teks ke Claude Code saat `Stop`: hook mengembalikan instruksi lanjutan | P0 |
| FR-23 | Reply teks ke agent tmux via `send-keys`, dengan konfirmasi pane target | P0 |
| FR-24 | Setiap aksi tercatat di audit log (siapa, kapan, dari kanal mana, isi) | P0 |
| FR-25 | Kapabilitas per sumber terlihat di UI (tombol yang tidak didukung disembunyikan, bukan error) | P0 |

**Notifikasi (Kentongan)**

| ID | Requirement | Prio |
| --- | --- | --- |
| FR-30 | Notifikasi desktop OS saat transisi ke `waiting_*`, `error`, `done` | P0 |
| FR-31 | Bot Telegram: notifikasi dengan tombol inline Approve/Deny dan reply-to-message untuk membalas | P1 |
| FR-32 | Webhook generik (POST JSON) untuk integrasi lain, misalnya Node-RED, Slack, ntfy | P1 |
| FR-33 | Debounce dan quiet hours | P2 |

## Arsitektur & adapter

Satu hub lokal menerima event dari semua pos dan meneruskan aksi kembali ke pos yang sama. Hanya pos yang tahu detail platform.

&#91;embedded content: arsitektur Ronda v1.0 · 4 pos, 1 hub, 4 kanal\]

Panah dua arah berarti sumber atau kanal itu mendukung aksi balik; notifikasi desktop dan webhook hanya satu arah.

| Komponen | Pilihan v1.0 | Alasan |
| --- | --- | --- |
| Hub | Python 3.11+, FastAPI, SQLite, WebSocket | Cepat dibangun, dan kontributor banyak yang familiar |
| Web UI | React + Vite, build statis yang di-serve oleh hub | Satu proses, tanpa server terpisah |
| Pos Claude Code | Script hook kecil (`ronda-hook`) untuk `PreToolUse`, `Notification`, `Stop`, `SessionStart`, `SessionEnd` | Jalur resmi untuk event dan keputusan |
| Pos tmux | Polling `tmux list-panes` + `capture-pane`, pola prompt per agent di YAML | Universal untuk CLI agent apa pun |
| Telegram | Long polling (tanpa webhook masuk) | Tidak perlu membuka port atau tunnel |
| Distribusi | `pipx install ronda`, image Docker, `ronda doctor` untuk cek setup | Instalasi satu perintah |

## Event schema, status & API

Semua pos menerjemahkan sinyal platform ke satu skema event yang sama. Core hanya mengenal skema ini, tidak mengenal platform.

```json
{
  "v": 1,
  "event_id": "01JC...",
  "ts": "2026-11-10T10:21:04Z",
  "source": "claude-code",
  "session_id": "claude:7f3a...",
  "agent": { "name": "claude", "model": "opus" },
  "workspace": { "cwd": "/home/u/aipy", "branch": "feat/ocr" },
  "host": { "app": "orca", "confidence": 0.9, "via": ["process_tree", "cwd"] },
  "type": "status_changed",
  "status": "waiting_approval",
  "summary": "Wants to run: docker compose up -d",
  "request": { "kind": "tool", "tool": "Bash", "input": "docker compose up -d" },
  "capabilities": ["approve", "deny", "reply", "open"]
}
```

**Status**

| Status | Arti | Masuk inbox "needs you"? |
| --- | --- | --- |
| `waiting_approval` | Agent meminta izin menjalankan tool | Ya, prioritas 1 |
| `waiting_input` | Agent selesai satu giliran dan menunggu instruksi | Ya, prioritas 2 |
| `error` | Agent crash atau error berulang | Ya, prioritas 3 |
| `running` | Agent sedang bekerja | Tidak |
| `done` / `ended` | Tugas selesai atau proses berhenti | Tidak (riwayat) |

**API hub (lokal)**

| Method | Path | Fungsi |
| --- | --- | --- |
| POST | `/v1/events` | Pos mengirim event |
| GET | `/v1/sessions?status=` | Daftar sesi dan status terkini |
| GET | `/v1/sessions/{id}/events` | Timeline sesi |
| POST | `/v1/sessions/{id}/actions` | `{type: approve, deny, reply, stop}` dari UI/Telegram |
| GET | `/v1/sessions/{id}/actions/next` | Long-poll pos untuk mengambil aksi (dipakai hook Claude Code) |
| WS | `/v1/stream` | Push event ke UI |

**Kontrak pos (adapter)**: proses terpisah yang POST event ke `/v1/events` dan mengambil jawaban dari `/v1/sessions/{id}/actions/next`, dengan `capabilities` per request. Bahasa pemrogramannya bebas; lihat `docs/writing-a-pos.md` dan `examples/pos_minimal.py`.

## Security & privacy

Ronda bisa menyetujui perintah shell atas nama user, jadi permukaan serangannya setara dengan akses terminal. Defaultnya harus aman.

- **Bind ke `127.0.0.1` saja** secara default. Akses remote hanya lewat Telegram (outbound polling, tanpa port terbuka) atau reverse proxy yang dipasang user sendiri.
- **Token lokal**: pos dan UI memakai token acak di `~/.ronda/token` (permission 600). Semua request tanpa token ditolak.
- **Telegram allowlist**: bot hanya merespons `chat_id` yang terdaftar saat pairing (`ronda pair telegram`).
- **Fail-closed ke terminal**: jika hub mati atau timeout, hook mengembalikan "tidak ada keputusan" sehingga agent kembali ke prompt aslinya. Ronda tidak pernah meng-auto-approve.
- **Redaksi**: input tool yang cocok dengan pola rahasia (`.env`, token, key) di-mask sebelum dikirim ke Telegram.
- **Data lokal**: SQLite di `~/.ronda/ronda.db` dengan retensi event default 7 hari. Tanpa telemetry di v1.0.
- **Aksi berisiko**: approve untuk command yang cocok dengan denylist (mis. `rm -rf`, `git push --force`) membutuhkan konfirmasi kedua di UI dan tidak bisa dilakukan dari Telegram.

## Non-functional requirements

| Aspek | Target v1.0 |
| --- | --- |
| Platform | Linux dan macOS penuh; Windows lewat WSL (pos tmux) plus hooks Claude Code native |
| Instalasi | `pipx install ronda` atau `docker run`; dari nol ke inbox pertama ≤ 5 menit |
| Latensi | Event ke UI < 1 dtk; event ke notifikasi Telegram < 3 dtk |
| Overhead | Daemon idle < 80 MB RAM, < 2% CPU dengan 10 sesi aktif |
| Keandalan | Hook gagal tidak boleh memblokir agent lebih dari timeout yang dikonfigurasi |
| Kompatibilitas | Skema event versioned (`v`), adapter diuji di CI terhadap fixture event tiap platform |
| Lisensi | MIT untuk core dan semua pos resmi |
| Dokumentasi | README dengan GIF demo 30 dtk, panduan menulis pos baru, dan threat model |

## Success metrics

Karena tanpa telemetry, metrik produk diukur dari dogfooding sendiri dan sinyal komunitas.

| Metrik | Target 90 hari setelah 1.0 | Cara ukur |
| --- | --- | --- |
| Waktu agent idle menunggu user | Turun ≥ 50% vs baseline 1 minggu tanpa Ronda | Hitung dari event log lokal sendiri (`ronda stats`) |
| Aksi dari Ronda vs dari aplikasi asli | ≥ 60% approve/reply dilakukan lewat Ronda | `ronda stats` |
| GitHub stars | 500 | GitHub |
| Pos dari komunitas | ≥ 3 pos baru di luar pos resmi | PR yang di-merge |
| Time-to-first-inbox | ≤ 5 menit untuk user baru | Uji 5 orang, direkam |

## Milestones & rilis open source

Usulannya: repo dibuka publik saat beta (25 Jan 2027), setelah approve/reply benar-benar stabil di pemakaian sendiri. Jadwal ini asumsi awal dan perlu disesuaikan dengan kapasitas kamu.

&#91;embedded content: usulan roadmap v1.0 · 5 milestone, beta, launch\]

Dogfooding dimulai begitu approve dan reply jalan, karena di situlah nilai inti Ronda diuji.

| Milestone | Deliverable | Exit criteria |
| --- | --- | --- |
| M0 Spike | Verifikasi hooks di Claude Code desktop, Orca CLI, dan API OpenBot; kumpulkan fingerprint (process tree + env var) tiap host di Windows, macOS, dan Linux sebagai dasar rule FR-08 | Semua open question teknis terjawab |
| M1 Core | Hub, skema event v1, pos Claude Code (read-only), inbox web | 1 hari kerja penuh tanpa event hilang |
| M2 Actions | Approve/deny, reply via `Stop`, notifikasi desktop, audit log | Approve dari Ronda ≥ 80% dari total approve |
| M3 Channels | Pos tmux, bot Telegram, webhook | Reply dari HP berhasil end-to-end |
| M4 Hardening | Pos Orca dan OpenBot, `ronda doctor`, dokumentasi, threat model | 5 user baru sampai inbox pertama ≤ 5 menit |

**Checklist rilis open source**

- [ ] Amankan nama: org GitHub, PyPI, npm, Docker Hub, dan domain
- [ ] Lisensi MIT, `CONTRIBUTING.md`, `SECURITY.md`, code of conduct
- [ ] README dengan GIF demo 30 detik: tiga agent, satu inbox, approve dari HP
- [ ] Template issue "New pos request" dan panduan menulis pos
- [ ] Contoh pos minimal (< 100 baris) sebagai starter untuk kontributor
- [ ] Launch post: Show HN, r/ClaudeAI, X/Twitter, serta komunitas dev Indonesia

## Risiko & open questions

**Risiko**

| Risiko | Dampak | Mitigasi |
| --- | --- | --- |
| Format hook/sesi Claude Code berubah | Pos Claude rusak | Pin versi skema, uji fixture di CI, dan pos tmux sebagai fallback |
| Deteksi status via teks terminal (tmux) tidak akurat | False positive "waiting" | Pola per agent bisa dikonfigurasi, plus indikator confidence di UI |
| Orca/OpenBot tidak punya API stabil | Dukungan hanya level tmux/proses | Mulai dari tmux; ajukan issue/PR ke upstream untuk hook resmi |
| Remote approve disalahgunakan | Command berbahaya dijalankan | Allowlist chat, denylist command, dan fail-closed |
| Pasar ramai, proyek tenggelam | Adopsi rendah | Fokus pada "lintas platform + reply" dan rilis dengan demo yang kuat |

**Open questions**

- [ ] OpenBot yang dipakai versi mana (nightly-labs atau meetopenbot), dan apakah punya API lokal untuk injeksi pesan?
- [ ] Apakah hooks di `~/.claude/settings.json` juga aktif untuk sesi Claude Code desktop? Perlu diverifikasi langsung.
- [ ] Apakah Orca CLI mengekspos status dan input agent, atau hanya kontrol worktree?
- [ ] OS utama untuk dogfooding: Windows, macOS, atau Linux?
- [ ] Bahasa implementasi core: Python (cepat, sesuai stack) atau Go/Rust (single binary, lebih mudah didistribusikan)?
- [ ] Di macOS, sejauh mana env var proses lain bisa dibaca? Kalau terblokir, fingerprint hanya mengandalkan process tree dan cwd.
