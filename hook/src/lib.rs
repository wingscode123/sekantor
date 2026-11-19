//! Native Claude Code hook forwarder (ADR-0026).
//!
//! Reads the hook payload on stdin and POSTs it unchanged, with a whitelisted part of the environment
//! and its own event id, to the hub's `POST /v1/hooks/claude`. The hub does the translating and the
//! host fingerprint, as the Python hook (`sekantor.pos.claude_code.hook`) did in-process.
//!
//! A hook never changes what the agent does: every path returns, nothing is printed, and `main` exits 0.
//! `sent.log` and `hook.log` keep the Python hook's line formats so `sekantor stats` reads both.

use serde_json::{Map, Value};
use std::collections::hash_map::RandomState;
use std::fs::{self, OpenOptions};
use std::hash::{BuildHasher, Hasher};
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4, TcpStream};
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub const HARD_TIMEOUT: Duration = Duration::from_millis(2000);
/// Windows takes ~2 s to refuse a closed loopback port; stay under the watchdog.
pub const HTTP_TIMEOUT: Duration = Duration::from_millis(1000);
/// SessionEnd is the one synchronous hook (5 s timeout), so it may wait a little longer.
pub const SESSION_END_HTTP_TIMEOUT: Duration = Duration::from_millis(1500);
pub const MAX_STDIN: usize = 4 * 1024 * 1024;
pub const LOG_MAX: u64 = 256 * 1024;
pub const SENT_MAX: u64 = 2 * 1024 * 1024;
pub const DEFAULT_PORT: u16 = 7878;
pub const HOOK_PATH: &str = "/v1/hooks/claude";
const MAX_RESPONSE: usize = 64 * 1024;
/// Kept free before the watchdog for writing sent.log and hook.log.
pub const LOG_RESERVE: Duration = Duration::from_millis(150);

/// What `run` did; only tests look at it.
#[derive(Debug, PartialEq, Eq)]
pub enum Outcome {
    /// Nothing sent: bad stdin, no home, or no token.
    Skipped(&'static str),
    /// The hub answered 2xx.
    Sent(u16),
    /// The hub answered 2xx with `"stored": false` (e.g. ignore_cwd): no sent.log line.
    Dropped,
    /// Logged as "hub unreachable (<kind>) <id>"; the kind is a Python exception name, as before.
    Failed(&'static str),
}

/// The process environment as UTF-8 pairs (names or values that are not UTF-8 are left out).
pub fn process_env() -> Vec<(String, String)> {
    std::env::vars_os()
        .filter_map(|(k, v)| Some((k.into_string().ok()?, v.into_string().ok()?)))
        .collect()
}

/// Forward one hook call. `windows` selects `USERPROFILE` and case-insensitive env names; `started` is
/// when the process began, so the request ends early enough for the logs to be written before the watchdog.
pub fn run<R: Read>(stdin: R, env: &[(String, String)], windows: bool, started: Instant) -> Outcome {
    let raw = match read_capped(stdin, MAX_STDIN) {
        Some(raw) => raw,
        None => return Outcome::Skipped("stdin"),
    };
    let payload = match parse_payload(&raw) {
        Some(payload) => payload,
        None => return Outcome::Skipped("payload"),
    };
    let home = match home_dir(env, windows) {
        Some(home) => home,
        None => return Outcome::Skipped("home"),
    };
    let token = match read_token(&home) {
        Some(token) => token,
        None => {
            log(&home, "no token: run `sekantor up` once");
            return Outcome::Skipped("token");
        }
    };
    let event_name = text_field(&payload, "hook_event_name");
    let whitelist = fs::read_to_string(home.join("hook-env.txt")).unwrap_or_default();
    let sent_env = select_env(&whitelist, env, windows);

    let now = SystemTime::now();
    let nanos = now.duration_since(UNIX_EPOCH).map(|d| d.as_nanos()).unwrap_or(0);
    let id = event_id(nanos, random_u32(nanos));
    let ts = utc_iso(now);
    let session = format!("claude:{}", text_field(&payload, "session_id"));
    // Written after the reply but with the pre-send `ts`, which is what `sekantor stats` reads.
    let sent = sent_line(&ts, &id, &session, &event_name);

    let port = hub_port(env, windows);
    let body = request_body(&id, &ts, payload, sent_env);
    let request = http_request(port, &token, &body);
    let addr = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port));
    let reply = match http_budget(&event_name, started.elapsed()) {
        Some(timeout) => post(addr, &request, timeout),
        None => Err("TimeoutError"),
    };
    let result = match reply {
        Ok((status, raw)) if (200..300).contains(&status) => {
            // The hub dropped it on purpose (e.g. ignore_cwd): not an attempt stats should count.
            if hub_dropped(&raw) {
                return Outcome::Dropped;
            }
            append_rotating(&home.join("sent.log"), &sent, SENT_MAX);
            return Outcome::Sent(status);
        }
        Ok(_) => "RuntimeError",
        Err(kind) => kind,
    };
    append_rotating(&home.join("sent.log"), &sent, SENT_MAX);
    // The event id lets `sekantor stats` match this line to the event, however late it is logged.
    log(&home, &format!("{}: hub unreachable ({}) {}", event_name, result, id));
    Outcome::Failed(result)
}

/// Time the request may take: the event's HTTP timeout, cut so that it ends at least `LOG_RESERVE`
/// before the watchdog. `None` when that leaves nothing.
pub fn http_budget(event_name: &str, elapsed: Duration) -> Option<Duration> {
    let left = HARD_TIMEOUT.checked_sub(elapsed)?.checked_sub(LOG_RESERVE)?;
    let budget = left.min(http_timeout(event_name));
    if budget.is_zero() {
        None
    } else {
        Some(budget)
    }
}

/// A 2xx reply whose JSON body says `"stored": false`. Anything unclear counts as stored.
fn hub_dropped(raw: &[u8]) -> bool {
    match response_body(raw).and_then(|b| serde_json::from_slice::<Value>(b).ok()) {
        Some(Value::Object(map)) => map.get("stored") == Some(&Value::Bool(false)),
        _ => false,
    }
}

/// All of `r` when it is at most `max` bytes; `None` when longer or unreadable.
pub fn read_capped<R: Read>(r: R, max: usize) -> Option<Vec<u8>> {
    let mut buf = Vec::new();
    r.take(max as u64 + 1).read_to_end(&mut buf).ok()?;
    if buf.len() > max {
        None
    } else {
        Some(buf)
    }
}

/// The hook payload when stdin is a UTF-8 JSON object.
pub fn parse_payload(raw: &[u8]) -> Option<Map<String, Value>> {
    match serde_json::from_slice::<Value>(raw) {
        Ok(Value::Object(map)) => Some(map),
        _ => None,
    }
}

/// A payload field as text; a missing field reads "None", as in the Python hook's f-strings.
fn text_field(payload: &Map<String, Value>, key: &str) -> String {
    match payload.get(key) {
        Some(Value::String(s)) => s.clone(),
        None | Some(Value::Null) => "None".to_string(),
        Some(other) => other.to_string(),
    }
}

fn lookup<'a>(env: &'a [(String, String)], name: &str, windows: bool) -> Option<&'a str> {
    env.iter()
        .find(|(k, _)| if windows { k.eq_ignore_ascii_case(name) } else { k == name })
        .map(|(_, v)| v.as_str())
}

/// `SEKANTOR_HOME`, else `%USERPROFILE%\.sekantor` (Windows) or `$HOME/.sekantor`.
pub fn home_dir(env: &[(String, String)], windows: bool) -> Option<PathBuf> {
    if let Some(home) = lookup(env, "SEKANTOR_HOME", windows).filter(|v| !v.is_empty()) {
        return Some(PathBuf::from(home));
    }
    let base = lookup(env, if windows { "USERPROFILE" } else { "HOME" }, windows).filter(|v| !v.is_empty())?;
    Some(PathBuf::from(base).join(".sekantor"))
}

/// The port of `SEKANTOR_URL`, else `SEKANTOR_PORT`, else 7878. The host is always 127.0.0.1.
pub fn hub_port(env: &[(String, String)], windows: bool) -> u16 {
    if let Some(url) = lookup(env, "SEKANTOR_URL", windows) {
        let rest = url.split_once("://").map(|(_, r)| r).unwrap_or(url);
        let authority = rest.split('/').next().unwrap_or("");
        if let Some(port) = authority.rsplit_once(':').and_then(|(_, p)| p.parse::<u16>().ok()) {
            return port;
        }
    }
    lookup(env, "SEKANTOR_PORT", windows)
        .and_then(|p| p.trim().parse::<u16>().ok())
        .unwrap_or(DEFAULT_PORT)
}

fn read_token(home: &Path) -> Option<String> {
    let token = fs::read_to_string(home.join("token")).ok()?;
    let token = token.trim();
    if token.is_empty() || token.chars().any(|c| c.is_control()) {
        return None; // a control character would break the request head
    }
    Some(token.to_string())
}

/// The env vars to send: names listed in `hook-env.txt` (one per line, written by the hub) plus
/// `CLAUDE_PID`. Nothing else leaves the process. Keys use the whitelist's spelling.
pub fn select_env(whitelist: &str, env: &[(String, String)], windows: bool) -> Map<String, Value> {
    let names = whitelist
        .lines()
        .map(str::trim)
        .filter(|n| !n.is_empty() && !n.starts_with('#'))
        .chain(std::iter::once("CLAUDE_PID"));
    let mut out = Map::new();
    for name in names {
        if let Some(value) = lookup(env, name, windows) {
            out.insert(name.to_string(), Value::from(value));
        }
    }
    out
}

/// 16 hex chars of nanoseconds + 8 random hex chars (`translate.new_event_id`).
pub fn event_id(time_ns: u128, random: u32) -> String {
    format!("{:016x}{:08x}", time_ns, random)
}

/// Four random bytes without a crate: the OS on Unix, else std's randomly seeded SipHash keys.
fn random_u32(seed: u128) -> u32 {
    #[cfg(unix)]
    {
        if let Ok(mut f) = fs::File::open("/dev/urandom") {
            let mut b = [0u8; 4];
            if f.read_exact(&mut b).is_ok() {
                return u32::from_le_bytes(b);
            }
        }
    }
    let mut h = RandomState::new().build_hasher();
    h.write_u128(seed);
    h.write_u32(std::process::id());
    let x = h.finish();
    (x ^ (x >> 32)) as u32
}

pub fn http_timeout(event_name: &str) -> Duration {
    if event_name == "SessionEnd" {
        SESSION_END_HTTP_TIMEOUT
    } else {
        HTTP_TIMEOUT
    }
}

/// `<ts> <event id> <session id> <what>`, the line `sekantor stats` compares with the db.
pub fn sent_line(ts: &str, id: &str, session: &str, what: &str) -> String {
    format!("{} {} {} {}\n", ts, id, session, what)
}

pub fn request_body(id: &str, ts: &str, payload: Map<String, Value>, env: Map<String, Value>) -> Vec<u8> {
    let mut body = Map::new();
    body.insert("v".to_string(), Value::from(1));
    body.insert("id".to_string(), Value::from(id));
    body.insert("ts".to_string(), Value::from(ts));
    body.insert("payload".to_string(), Value::Object(payload));
    body.insert("env".to_string(), Value::Object(env));
    serde_json::to_vec(&Value::Object(body)).unwrap_or_default()
}

pub fn http_request(port: u16, token: &str, body: &[u8]) -> Vec<u8> {
    let head = format!(
        "POST {} HTTP/1.1\r\nHost: 127.0.0.1:{}\r\nAuthorization: Bearer {}\r\nConnection: close\r\n\
         Content-Type: application/json\r\nContent-Length: {}\r\n\r\n",
        HOOK_PATH,
        port,
        token,
        body.len()
    );
    let mut out = head.into_bytes();
    out.extend_from_slice(body);
    out
}

/// Send `request` and return the status and the raw response. Connect, write and read all share one
/// deadline, `timeout` from now, so a hub that accepts and never answers costs `timeout`, not more.
/// Reading stops at EOF or once the head and `Content-Length` body bytes are in.
pub fn post(addr: SocketAddr, request: &[u8], timeout: Duration) -> Result<(u16, Vec<u8>), &'static str> {
    let deadline = Instant::now() + timeout;
    let mut stream = TcpStream::connect_timeout(&addr, timeout).map_err(|e| err_name(&e))?;
    stream.set_write_timeout(Some(remaining(deadline)?)).map_err(|e| err_name(&e))?;
    stream.write_all(request).map_err(|e| err_name(&e))?;
    let mut response = Vec::new();
    let mut buf = [0u8; 4096];
    loop {
        let left = match remaining(deadline) {
            Ok(left) => left,
            Err(kind) => return with_status(response, kind),
        };
        stream.set_read_timeout(Some(left)).map_err(|e| err_name(&e))?;
        match stream.read(&mut buf) {
            Ok(0) => break,
            Ok(n) => {
                response.extend_from_slice(&buf[..n]);
                if response.len() > MAX_RESPONSE || response_complete(&response) {
                    break;
                }
            }
            Err(e) if e.kind() == io::ErrorKind::Interrupted => continue,
            Err(e) => return with_status(response, err_name(&e)),
        }
    }
    with_status(response, "RuntimeError")
}

/// A response whose status line arrived counts as answered, even if the rest did not.
fn with_status(response: Vec<u8>, otherwise: &'static str) -> Result<(u16, Vec<u8>), &'static str> {
    match parse_status(&response) {
        Some(status) => Ok((status, response)),
        None => Err(otherwise),
    }
}

fn find(haystack: &[u8], needle: &[u8]) -> Option<usize> {
    haystack.windows(needle.len()).position(|w| w == needle)
}

/// `Content-Length` from a response or request head (the bytes before the blank line).
fn content_length(head: &[u8]) -> Option<usize> {
    let head = std::str::from_utf8(head).ok()?;
    head.split("\r\n").skip(1).find_map(|line| {
        let (name, value) = line.split_once(':')?;
        if name.trim().eq_ignore_ascii_case("content-length") {
            value.trim().parse::<usize>().ok()
        } else {
            None
        }
    })
}

/// The head is in and so are all `Content-Length` body bytes (without that header: wait for EOF).
fn response_complete(raw: &[u8]) -> bool {
    match find(raw, b"\r\n\r\n") {
        Some(end) => matches!(content_length(&raw[..end]), Some(n) if raw.len() >= end + 4 + n),
        None => false,
    }
}

/// The body after the blank line, cut to `Content-Length`; `None` while it is incomplete.
fn response_body(raw: &[u8]) -> Option<&[u8]> {
    let end = find(raw, b"\r\n\r\n")?;
    let rest = &raw[end + 4..];
    match content_length(&raw[..end]) {
        Some(n) if rest.len() >= n => Some(&rest[..n]),
        Some(_) => None,
        None => Some(rest),
    }
}

fn remaining(deadline: Instant) -> Result<Duration, &'static str> {
    let now = Instant::now();
    if now >= deadline {
        Err("TimeoutError")
    } else {
        Ok(deadline - now)
    }
}

/// The status code of a complete `HTTP/1.x NNN ...` line.
fn parse_status(response: &[u8]) -> Option<u16> {
    let end = response.windows(2).position(|w| w == b"\r\n")?;
    let line = std::str::from_utf8(&response[..end]).ok()?;
    let mut parts = line.split(' ');
    if !parts.next()?.starts_with("HTTP/") {
        return None;
    }
    parts.next()?.parse::<u16>().ok()
}

/// The Python exception name the old hook logged for the same failure.
fn err_name(e: &io::Error) -> &'static str {
    match e.kind() {
        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock => "TimeoutError",
        io::ErrorKind::ConnectionRefused => "ConnectionRefusedError",
        io::ErrorKind::ConnectionReset => "ConnectionResetError",
        io::ErrorKind::ConnectionAborted => "ConnectionAbortedError",
        io::ErrorKind::BrokenPipe => "BrokenPipeError",
        _ => "OSError",
    }
}

/// Append one line in one write (hooks run in parallel), first moving a file past `max` to `<name>.1`.
pub fn append_rotating(path: &Path, line: &str, max: u64) {
    if let Ok(meta) = fs::metadata(path) {
        if meta.len() > max {
            let mut rotated = path.as_os_str().to_owned();
            rotated.push(".1");
            let _ = fs::rename(path, PathBuf::from(rotated));
        }
    }
    let mut options = OpenOptions::new();
    options.create(true).append(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    if let Ok(mut f) = options.open(path) {
        let _ = f.write_all(line.as_bytes());
    }
}

fn log(home: &Path, message: &str) {
    append_rotating(&home.join("hook.log"), &format!("{} {}\n", local_stamp(), message), LOG_MAX);
}

/// ISO 8601 UTC with microseconds, e.g. `2026-11-17T09:30:00.123456+00:00` (Python's
/// `datetime.fromisoformat` reads it; the hub stores it as the event's `ts`).
pub fn utc_iso(t: SystemTime) -> String {
    let d = t.duration_since(UNIX_EPOCH).unwrap_or_default();
    let (y, mo, day, h, mi, s) = utc_parts(d.as_secs());
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}.{:06}+00:00", y, mo, day, h, mi, s, d.subsec_micros())
}

type Parts = (i64, u32, u32, u32, u32, u32);

fn utc_parts(secs: u64) -> Parts {
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    let (y, mo, d) = civil_from_days(days);
    (y, mo, d, (rem / 3600) as u32, (rem % 3600 / 60) as u32, (rem % 60) as u32)
}

/// Days since 1970-01-01 to (year, month, day), proleptic Gregorian (H. Hinnant's algorithm).
fn civil_from_days(days: i64) -> (i64, u32, u32) {
    let z = days + 719_468;
    let era = (if z >= 0 { z } else { z - 146_096 }) / 146_097;
    let doe = (z - era * 146_097) as u64;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    let y = yoe as i64 + era * 400;
    (if m <= 2 { y + 1 } else { y }, m, d)
}

/// `%Y-%m-%dT%H:%M:%S` in local time: `sekantor stats` parses hook.log stamps as local time.
pub fn local_stamp() -> String {
    let (y, mo, d, h, mi, s) = local_now().unwrap_or_else(|| {
        // No local-time source on this target: UTC, which stats would misread by the UTC offset.
        let secs = SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0);
        utc_parts(secs)
    });
    format!("{:04}-{:02}-{:02}T{:02}:{:02}:{:02}", y, mo, d, h, mi, s)
}

#[cfg(windows)]
fn local_now() -> Option<Parts> {
    #[repr(C)]
    #[allow(dead_code)]
    struct WinSystemTime {
        year: u16,
        month: u16,
        day_of_week: u16,
        day: u16,
        hour: u16,
        minute: u16,
        second: u16,
        milliseconds: u16,
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn GetLocalTime(out: *mut WinSystemTime);
    }
    let mut st = WinSystemTime {
        year: 0,
        month: 0,
        day_of_week: 0,
        day: 0,
        hour: 0,
        minute: 0,
        second: 0,
        milliseconds: 0,
    };
    unsafe { GetLocalTime(&mut st) };
    if st.year == 0 {
        return None;
    }
    Some((st.year as i64, st.month as u32, st.day as u32, st.hour as u32, st.minute as u32, st.second as u32))
}

#[cfg(all(unix, target_pointer_width = "64"))]
fn local_now() -> Option<Parts> {
    // `struct tm`: nine ints, then platform-specific fields (glibc and macOS: tm_gmtoff, tm_zone),
    // covered by an oversized tail. time_t is 64-bit on these targets.
    #[repr(C)]
    #[allow(dead_code)]
    struct Tm {
        sec: i32,
        min: i32,
        hour: i32,
        mday: i32,
        mon: i32,
        year: i32,
        wday: i32,
        yday: i32,
        isdst: i32,
        tail: [u64; 8],
    }
    extern "C" {
        fn tzset();
        fn localtime_r(t: *const i64, out: *mut Tm) -> *mut Tm;
    }
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).ok()?.as_secs() as i64;
    let mut tm = Tm { sec: 0, min: 0, hour: 0, mday: 0, mon: 0, year: 0, wday: 0, yday: 0, isdst: 0, tail: [0; 8] };
    let ok = unsafe {
        tzset();
        !localtime_r(&secs, &mut tm).is_null()
    };
    if !ok {
        return None;
    }
    Some(((tm.year + 1900) as i64, (tm.mon + 1) as u32, tm.mday as u32, tm.hour as u32, tm.min as u32, tm.sec as u32))
}

#[cfg(not(any(windows, all(unix, target_pointer_width = "64"))))]
fn local_now() -> Option<Parts> {
    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    use std::net::TcpListener;
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::mpsc;
    use std::thread;

    /// A temporary home, removed when the test ends. Tests never use the real home or port 7878.
    struct TempHome(PathBuf);

    impl Drop for TempHome {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    impl std::ops::Deref for TempHome {
        type Target = Path;
        fn deref(&self) -> &Path {
            &self.0
        }
    }

    fn temp_home(tag: &str) -> TempHome {
        static N: AtomicU32 = AtomicU32::new(0);
        let dir = std::env::temp_dir().join(format!(
            "sekantor-hook-test-{}-{}-{}",
            std::process::id(),
            tag,
            N.fetch_add(1, Ordering::SeqCst)
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        TempHome(dir)
    }

    fn home_with_token(tag: &str) -> TempHome {
        let home = temp_home(tag);
        fs::write(home.join("token"), "tok123\n").unwrap();
        home
    }

    fn owned(pairs: &[(&str, &str)]) -> Vec<(String, String)> {
        pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()
    }

    fn env_for(home: &Path, port: u16, extra: &[(&str, &str)]) -> Vec<(String, String)> {
        let mut env = owned(extra);
        env.push(("SEKANTOR_HOME".to_string(), home.to_string_lossy().into_owned()));
        env.push(("SEKANTOR_PORT".to_string(), port.to_string()));
        env
    }

    fn is_event_id(id: &str) -> bool {
        id.len() == 24 && id.chars().all(|c| c.is_ascii_digit() || ('a'..='f').contains(&c))
    }

    fn read_request(s: &mut TcpStream) -> Vec<u8> {
        let mut data = Vec::new();
        let mut buf = [0u8; 4096];
        loop {
            if let Some(end) = find(&data, b"\r\n\r\n") {
                let len = content_length(&data[..end]).unwrap_or(0);
                if data.len() >= end + 4 + len {
                    return data;
                }
            }
            match s.read(&mut buf) {
                Ok(0) | Err(_) => return data,
                Ok(n) => data.extend_from_slice(&buf[..n]),
            }
        }
    }

    /// A hub that answers one request with `status_line` and `body`, keeps the connection open for
    /// `hold`, and hands the raw request to the test.
    fn fake_hub(status_line: &'static str, body: &'static str, hold: Duration) -> (u16, mpsc::Receiver<Vec<u8>>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let (tx, rx) = mpsc::channel();
        thread::spawn(move || {
            if let Ok((mut s, _)) = listener.accept() {
                s.set_read_timeout(Some(Duration::from_secs(5))).unwrap();
                let req = read_request(&mut s);
                let reply = format!(
                    "{}\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                    status_line,
                    body.len(),
                    body
                );
                let _ = s.write_all(reply.as_bytes());
                let _ = tx.send(req);
                thread::sleep(hold);
            }
        });
        (port, rx)
    }

    const STORED: &str = r#"{"stored": true, "event_id": "x"}"#;
    const PRE_TOOL_USE: &[u8] =
        br#"{"session_id":"abc","hook_event_name":"PreToolUse","tool_name":"Read","cwd":"/w","tool_input":{"file_path":"/w/a.txt"}}"#;

    fn ms(n: u64) -> Duration {
        Duration::from_millis(n)
    }

    #[test]
    fn posts_raw_payload_with_whitelisted_env_only() {
        let home = home_with_token("post");
        fs::write(
            home.join("hook-env.txt"),
            "TERM_PROGRAM\nCLAUDE_PID\nORCA_AGENT_SESSION_ID\nORCA_TERMINAL_HANDLE\n",
        ).unwrap();
        let (port, rx) = fake_hub("HTTP/1.1 202 Accepted", STORED, ms(0));
        let env = env_for(
            &home,
            port,
            &[
                ("TERM_PROGRAM", "vscode"),
                ("CLAUDE_PID", "4242"),
                ("ORCA_AGENT_SESSION_ID", "agent-id"),
                ("ORCA_TERMINAL_HANDLE", "structworker_id"),
                ("ANTHROPIC_API_KEY", "sk-secret"),
            ],
        );

        assert_eq!(run(PRE_TOOL_USE, &env, false, Instant::now()), Outcome::Sent(202));

        let req = rx.recv_timeout(Duration::from_secs(5)).unwrap();
        let end = find(&req, b"\r\n\r\n").unwrap();
        let head = std::str::from_utf8(&req[..end]).unwrap();
        let mut lines = head.split("\r\n");
        assert_eq!(lines.next(), Some("POST /v1/hooks/claude HTTP/1.1"));
        let headers: Vec<&str> = lines.collect();
        let body_bytes = &req[end + 4..];
        for expected in [
            format!("Host: 127.0.0.1:{}", port),
            "Authorization: Bearer tok123".to_string(),
            "Connection: close".to_string(),
            "Content-Type: application/json".to_string(),
            format!("Content-Length: {}", body_bytes.len()),
        ] {
            assert!(headers.contains(&expected.as_str()), "missing {:?} in {:?}", expected, headers);
        }

        let body: Value = serde_json::from_slice(body_bytes).unwrap();
        assert_eq!(body["v"], 1);
        let id = body["id"].as_str().unwrap();
        assert!(is_event_id(id), "{}", id);
        let ts = body["ts"].as_str().unwrap();
        assert!(ts.ends_with("+00:00") && ts.len() == 32, "{}", ts);
        assert_eq!(body["payload"], serde_json::from_slice::<Value>(PRE_TOOL_USE).unwrap());
        assert_eq!(body["env"], json!({
            "TERM_PROGRAM": "vscode", "CLAUDE_PID": "4242",
            "ORCA_AGENT_SESSION_ID": "agent-id", "ORCA_TERMINAL_HANDLE": "structworker_id"
        }));
        assert_eq!(body.as_object().unwrap().len(), 5);
        assert!(!String::from_utf8_lossy(&req).contains("sk-secret"));

        let sent = fs::read_to_string(home.join("sent.log")).unwrap();
        assert_eq!(sent, format!("{} {} claude:abc PreToolUse\n", ts, id));
        assert!(!home.join("hook.log").exists());
    }

    #[test]
    fn event_the_hub_did_not_store_is_not_in_sent_log() {
        let home = home_with_token("dropped");
        let (port, rx) = fake_hub("HTTP/1.1 202 Accepted", r#"{"stored": false}"#, ms(0));
        let env = env_for(&home, port, &[]);
        assert_eq!(run(PRE_TOOL_USE, &env, false, Instant::now()), Outcome::Dropped);
        rx.recv_timeout(Duration::from_secs(5)).unwrap();
        assert!(!home.join("sent.log").exists());
        assert!(!home.join("hook.log").exists());
    }

    #[test]
    fn unclear_2xx_body_still_counts_as_sent() {
        for body in ["", "not json", "[false]", r#"{"stored": "no"}"#] {
            let home = home_with_token("unclear");
            let (port, rx) = fake_hub("HTTP/1.1 202 Accepted", body, ms(0));
            let env = env_for(&home, port, &[]);
            assert_eq!(run(PRE_TOOL_USE, &env, false, Instant::now()), Outcome::Sent(202), "{:?}", body);
            rx.recv_timeout(Duration::from_secs(5)).unwrap();
            assert_eq!(fs::read_to_string(home.join("sent.log")).unwrap().lines().count(), 1, "{:?}", body);
        }
    }

    #[test]
    fn stops_reading_once_content_length_bytes_are_in() {
        let (port, _rx) = fake_hub("HTTP/1.1 202 Accepted", STORED, Duration::from_secs(3));
        let addr = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port));
        let start = Instant::now();
        let (status, raw) = post(addr, b"POST / HTTP/1.1\r\nContent-Length: 0\r\n\r\n", HTTP_TIMEOUT).unwrap();
        assert!(start.elapsed() < ms(900), "{:?}", start.elapsed());
        assert_eq!(status, 202);
        assert_eq!(response_body(&raw), Some(STORED.as_bytes()));
    }

    #[test]
    fn response_body_honours_content_length() {
        assert_eq!(response_body(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}xx"), Some(&b"{}"[..]));
        assert_eq!(response_body(b"HTTP/1.1 200 OK\r\ncontent-length: 5\r\n\r\n{}"), None);
        assert_eq!(response_body(b"HTTP/1.1 200 OK\r\n\r\n{}"), Some(&b"{}"[..]));
        assert_eq!(response_body(b"HTTP/1.1 200 OK\r\n"), None);
        assert!(hub_dropped(b"HTTP/1.1 202 Accepted\r\nContent-Length: 17\r\n\r\n{\"stored\": false}"));
        assert!(!hub_dropped(b"HTTP/1.1 202 Accepted\r\nContent-Length: 16\r\n\r\n{\"stored\": true}"));
    }

    #[test]
    fn env_whitelist_sends_listed_names_and_claude_pid_only() {
        let env = owned(&[("ANTHROPIC_API_KEY", "sk"), ("TERM_PROGRAM", "vscode"), ("CLAUDE_PID", "7")]);
        let got = select_env("# rules\nTERM_PROGRAM\n\nWT_SESSION\n", &env, false);
        assert_eq!(Value::Object(got), json!({"TERM_PROGRAM": "vscode", "CLAUDE_PID": "7"}));
        // No hook-env.txt yet (hub never started): only CLAUDE_PID.
        assert_eq!(Value::Object(select_env("", &env, false)), json!({"CLAUDE_PID": "7"}));
    }

    #[test]
    fn env_names_match_case_insensitively_on_windows_only() {
        let env = owned(&[("Wt_Session", "1"), ("anthropic_api_key", "sk")]);
        assert_eq!(Value::Object(select_env("WT_SESSION\r\n", &env, true)), json!({"WT_SESSION": "1"}));
        assert_eq!(Value::Object(select_env("WT_SESSION\n", &env, false)), json!({}));
    }

    #[test]
    fn event_id_is_16_hex_time_and_8_hex_random() {
        assert_eq!(event_id(0x1234, 0xab), "0000000000001234000000ab");
        let ns = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos();
        let a = event_id(ns, random_u32(ns));
        assert!(is_event_id(&a), "{}", a);
        assert_eq!(&a[..16], &format!("{:016x}", ns)[..]);
        let ids: std::collections::HashSet<String> = (0..64).map(|_| event_id(ns, random_u32(ns))).collect();
        assert!(ids.len() > 60, "random part repeats: {:?}", ids);
    }

    #[test]
    fn utc_timestamps_match_python_isoformat() {
        let at = |secs: u64, micros: u64| utc_iso(UNIX_EPOCH + Duration::from_secs(secs) + Duration::from_micros(micros));
        assert_eq!(at(0, 0), "1970-01-01T00:00:00.000000+00:00");
        assert_eq!(at(951_782_400, 0), "2000-02-29T00:00:00.000000+00:00");
        assert_eq!(at(1_700_000_000, 123_456), "2023-11-14T22:13:20.123456+00:00");
        assert_eq!(at(1_709_210_096, 7), "2024-02-29T12:34:56.000007+00:00");
        assert_eq!(at(4_102_444_799, 0), "2099-12-31T23:59:59.000000+00:00");
    }

    #[test]
    fn local_stamp_has_the_stats_format() {
        let s = local_stamp();
        let b = s.as_bytes();
        assert_eq!(s.len(), 19, "{}", s);
        assert_eq!((b[4], b[7], b[10], b[13], b[16]), (b'-', b'-', b'T', b':', b':'), "{}", s);
        assert_eq!(s.chars().filter(|c| c.is_ascii_digit()).count(), 14, "{}", s);
    }

    #[test]
    fn hub_that_never_answers_times_out_after_the_http_timeout() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap(); // never accepts, never answers
        let addr = listener.local_addr().unwrap();
        let start = Instant::now();
        let result = post(addr, b"POST / HTTP/1.1\r\n\r\n", HTTP_TIMEOUT);
        let took = start.elapsed();
        assert_eq!(result, Err("TimeoutError"));
        assert!(took >= ms(900) && took < ms(1900), "{:?}", took);
        drop(listener);
    }

    #[test]
    fn silent_hub_logs_one_unreachable_line_with_the_event_id() {
        let home = home_with_token("silent");
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let env = env_for(&home, listener.local_addr().unwrap().port(), &[]);
        let start = Instant::now();
        assert_eq!(run(PRE_TOOL_USE, &env, false, start), Outcome::Failed("TimeoutError"));
        assert!(start.elapsed() < ms(1900), "{:?}", start.elapsed());

        let sent = fs::read_to_string(home.join("sent.log")).unwrap();
        assert_eq!(sent.lines().count(), 1);
        let id = sent.split(' ').nth(1).unwrap().to_string();
        let log = fs::read_to_string(home.join("hook.log")).unwrap();
        assert_eq!(log.lines().count(), 1);
        assert_eq!(&log[19..], format!(" PreToolUse: hub unreachable (TimeoutError) {}\n", id));
        drop(listener);
    }

    #[test]
    fn no_time_left_skips_the_request_but_still_logs() {
        let home = home_with_token("late");
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let env = env_for(&home, listener.local_addr().unwrap().port(), &[]);
        let started = Instant::now().checked_sub(ms(1900)).unwrap();
        let start = Instant::now();
        assert_eq!(run(PRE_TOOL_USE, &env, false, started), Outcome::Failed("TimeoutError"));
        assert!(start.elapsed() < ms(500), "{:?}", start.elapsed());
        assert!(listener.accept().is_err(), "the hook connected with no time left");
        assert_eq!(fs::read_to_string(home.join("sent.log")).unwrap().lines().count(), 1);
        let log = fs::read_to_string(home.join("hook.log")).unwrap();
        assert!(log.contains(" PreToolUse: hub unreachable (TimeoutError) "), "{}", log);
    }

    #[test]
    fn http_budget_leaves_time_for_the_logs() {
        assert_eq!(http_budget("PreToolUse", ms(0)), Some(ms(1000)));
        assert_eq!(http_budget("SessionEnd", ms(0)), Some(ms(1500)));
        assert_eq!(http_budget("SessionEnd", ms(600)), Some(ms(1250)));
        assert_eq!(http_budget("PreToolUse", ms(1840)), Some(ms(10)));
        assert_eq!(http_budget("PreToolUse", ms(1850)), None);
        assert_eq!(http_budget("PreToolUse", ms(5000)), None);
    }

    #[test]
    fn refused_port_is_an_error_within_the_timeout() {
        let port = {
            let l = TcpListener::bind("127.0.0.1:0").unwrap();
            l.local_addr().unwrap().port()
        };
        let addr = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, port));
        let start = Instant::now();
        match post(addr, b"POST / HTTP/1.1\r\n\r\n", HTTP_TIMEOUT) {
            // Something else took the freed port in the meantime: nothing to check.
            Ok(_) => {}
            // Windows retries a refused loopback connect for ~2 s, so it ends as a timeout there.
            Err(kind) => assert!(
                kind == "ConnectionRefusedError" || kind == "TimeoutError" || kind == "ConnectionResetError",
                "{}",
                kind
            ),
        }
        assert!(start.elapsed() < ms(1900), "{:?}", start.elapsed());
    }

    #[test]
    fn non_2xx_answer_is_logged_as_unreachable() {
        let home = home_with_token("401");
        let (port, rx) = fake_hub("HTTP/1.1 401 Unauthorized", r#"{"detail": "no"}"#, ms(0));
        let env = env_for(&home, port, &[]);
        assert_eq!(run(PRE_TOOL_USE, &env, false, Instant::now()), Outcome::Failed("RuntimeError"));
        rx.recv_timeout(Duration::from_secs(5)).unwrap();
        assert_eq!(fs::read_to_string(home.join("sent.log")).unwrap().lines().count(), 1);
        let log = fs::read_to_string(home.join("hook.log")).unwrap();
        assert!(log.contains(" PreToolUse: hub unreachable (RuntimeError) "), "{}", log);
    }

    #[test]
    fn bad_or_oversized_stdin_sends_nothing() {
        let home = home_with_token("bad");
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let env = env_for(&home, listener.local_addr().unwrap().port(), &[]);

        let inputs: [&[u8]; 6] = [
            b"[1, 2]",
            b"\"text\"",
            b"42",
            b"not json",
            b"\xff\xfe{\"a\": 1}",
            b"{\"a\":\"\xff\"}", // invalid UTF-8 inside a string
        ];
        for input in inputs {
            assert_eq!(run(input, &env, false, Instant::now()), Outcome::Skipped("payload"), "{:?}", input);
        }
        let mut big = b"{\"a\":\"".to_vec();
        big.extend(std::iter::repeat(b'x').take(MAX_STDIN));
        big.extend_from_slice(b"\"}");
        assert_eq!(run(&big[..], &env, false, Instant::now()), Outcome::Skipped("stdin"));

        assert!(listener.accept().is_err(), "the hook connected to the hub");
        assert!(!home.join("sent.log").exists());
        assert!(!home.join("hook.log").exists());
    }

    #[test]
    fn stdin_cap_is_inclusive() {
        assert_eq!(read_capped(&[1u8; 10][..], 10).map(|b| b.len()), Some(10));
        assert_eq!(read_capped(&[1u8; 11][..], 10), None);
    }

    #[test]
    fn missing_token_logs_the_hint_and_sends_nothing() {
        let home = temp_home("notoken");
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        listener.set_nonblocking(true).unwrap();
        let env = env_for(&home, listener.local_addr().unwrap().port(), &[]);
        assert_eq!(run(PRE_TOOL_USE, &env, false, Instant::now()), Outcome::Skipped("token"));
        assert!(listener.accept().is_err());
        let log = fs::read_to_string(home.join("hook.log")).unwrap();
        assert_eq!(&log[19..], " no token: run `sekantor up` once\n");
        assert!(!home.join("sent.log").exists());
    }

    #[test]
    fn sent_log_line_format_and_rotation() {
        assert_eq!(sent_line("T", "id1", "claude:s", "Stop"), "T id1 claude:s Stop\n");
        let home = temp_home("rotate");
        let path = home.join("sent.log");
        append_rotating(&path, "first line of twenty\n", 10);
        append_rotating(&path, "second\n", 10);
        assert_eq!(fs::read_to_string(home.join("sent.log.1")).unwrap(), "first line of twenty\n");
        assert_eq!(fs::read_to_string(&path).unwrap(), "second\n");
    }

    #[test]
    fn home_and_port_resolution() {
        let env = owned(&[("USERPROFILE", "C:\\Users\\me"), ("HOME", "/home/me")]);
        assert_eq!(home_dir(&env, true), Some(PathBuf::from("C:\\Users\\me").join(".sekantor")));
        assert_eq!(home_dir(&env, false), Some(PathBuf::from("/home/me").join(".sekantor")));
        let env = owned(&[("SEKANTOR_HOME", "/x/home"), ("HOME", "/home/me")]);
        assert_eq!(home_dir(&env, false), Some(PathBuf::from("/x/home")));
        assert_eq!(home_dir(&[], false), None);

        assert_eq!(hub_port(&[], false), DEFAULT_PORT);
        assert_eq!(hub_port(&owned(&[("SEKANTOR_PORT", "7901")]), false), 7901);
        let both = owned(&[("SEKANTOR_URL", "http://127.0.0.1:7900/"), ("SEKANTOR_PORT", "7901")]);
        assert_eq!(hub_port(&both, false), 7900);
        assert_eq!(hub_port(&owned(&[("sekantor_port", "7902")]), true), 7902);
    }

    #[test]
    fn session_end_waits_longer() {
        assert_eq!(http_timeout("SessionEnd"), ms(1500));
        assert_eq!(http_timeout("PreToolUse"), ms(1000));
    }

    #[test]
    fn status_parsing() {
        assert_eq!(parse_status(b"HTTP/1.1 202 Accepted\r\n"), Some(202));
        assert_eq!(parse_status(b"HTTP/1.1 202 Acc"), None);
        assert_eq!(parse_status(b"garbage\r\n"), None);
    }
}
