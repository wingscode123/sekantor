//! Talking to the local hub: where it lives, its token, starting it, and the HTTP calls the shell makes.
//!
//! No Tauri types here, so `cargo test` covers it. Every request goes to 127.0.0.1 only.

use std::ffi::OsString;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::time::{Duration, Instant};

pub const DEFAULT_PORT: u16 = 7878;
pub const HTTP_TIMEOUT: Duration = Duration::from_secs(5);
pub const HTTP_TRIES: u32 = 3;
pub const HTTP_PAUSE: Duration = Duration::from_secs(1);
pub const POLL_EVERY: Duration = Duration::from_millis(500);
pub const POLL_FOR: Duration = Duration::from_secs(30);
/// After `setup --apply` the service task starts a hub; give it this long before starting our own.
pub const SERVICE_GRACE: Duration = Duration::from_secs(15);

/// `SEKANTOR_HOME`, or `~/.sekantor` (same rule as `sekantor.config.home`).
pub fn home_dir() -> PathBuf {
    home_dir_from(|k| std::env::var(k).ok())
}

pub fn home_dir_from(env: impl Fn(&str) -> Option<String>) -> PathBuf {
    if let Some(h) = env("SEKANTOR_HOME").filter(|h| !h.is_empty()) {
        return PathBuf::from(h);
    }
    let user = env("USERPROFILE")
        .filter(|h| !h.is_empty())
        .or_else(|| env("HOME").filter(|h| !h.is_empty()))
        .unwrap_or_else(|| ".".to_string());
    PathBuf::from(user).join(".sekantor")
}

/// The hub token from `<home>/token`, trimmed; `None` when missing or empty.
pub fn read_token(home: &Path) -> Option<String> {
    let t = std::fs::read_to_string(home.join("token")).ok()?;
    let t = t.trim();
    (!t.is_empty()).then(|| t.to_string())
}

/// `SEKANTOR_PORT`, or 7878 (same rule as `sekantor.config.port`).
pub fn hub_port() -> u16 {
    port_from(std::env::var("SEKANTOR_PORT").ok())
}

pub fn port_from(value: Option<String>) -> u16 {
    value.and_then(|v| v.trim().parse().ok()).unwrap_or(DEFAULT_PORT)
}

pub fn base_url(port: u16) -> String {
    format!("http://127.0.0.1:{port}")
}

pub fn login_url(port: u16, code: &str) -> String {
    format!("http://127.0.0.1:{port}/?login={code}")
}

/// The code inside the `path` that `POST /v1/login-code` returns (`/?login=<code>`).
pub fn code_from_path(path: &str) -> Option<String> {
    let code = path.strip_prefix("/?login=")?;
    (!code.is_empty() && !code.contains(|c: char| matches!(c, '&' | '#' | '/'))).then(|| code.to_string())
}

/// A monotonic clock for `wait_for` / `ensure_hub`: time since it was made.
pub fn monotonic() -> impl Fn() -> Duration {
    let t0 = Instant::now();
    move || t0.elapsed()
}

/// Poll `health` every 500 ms until it answers or `limit` has passed on `clock`. The limit is wall
/// time, so a health check that itself takes seconds (a busy hub) does not stretch the wait.
pub fn wait_for(
    health: impl Fn() -> bool,
    sleep: impl Fn(Duration),
    clock: impl Fn() -> Duration,
    limit: Duration,
) -> bool {
    let start = clock();
    while clock().saturating_sub(start) < limit {
        sleep(POLL_EVERY);
        if health() {
            return true;
        }
    }
    false
}

/// Start the hub if it does not answer: `launch` once, then poll `health` every 500 ms for up to 30 s
/// on `clock`. Tests pass a fake `sleep` and `clock`, so they run instantly.
pub fn ensure_hub(
    launch: impl Fn() -> io::Result<()>,
    health: impl Fn() -> bool,
    sleep: impl Fn(Duration),
    clock: impl Fn() -> Duration,
) -> Result<(), String> {
    if health() {
        return Ok(());
    }
    launch().map_err(|e| format!("could not start the SeKantor hub: {e}"))?;
    if wait_for(health, sleep, clock, POLL_FOR) {
        return Ok(());
    }
    Err(format!(
        "the SeKantor hub did not answer within {} s (see hub.log in the .sekantor folder)",
        POLL_FOR.as_secs()
    ))
}

#[derive(Debug, Clone, PartialEq)]
pub enum HttpError {
    /// Nothing listens on the port: retrying does not help.
    Refused,
    /// The hub answered with a 4xx (bad or missing token, ...): retrying does not help.
    Rejected(u16),
    /// Timeout, 5xx or a broken answer: the hub may just be busy, so try again.
    Failed(String),
}

impl std::fmt::Display for HttpError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            HttpError::Refused => write!(f, "the hub is not running"),
            HttpError::Rejected(code) => write!(f, "the hub refused the request (HTTP {code})"),
            HttpError::Failed(why) => write!(f, "the hub did not answer: {why}"),
        }
    }
}

/// Call `f` up to `tries` times, pausing `pause` between tries, while it fails with `Failed`.
/// A busy hub (the owner's laptop pages heavily) answers late, not never.
pub fn retry<T>(
    tries: u32,
    pause: Duration,
    sleep: impl Fn(Duration),
    mut f: impl FnMut() -> Result<T, HttpError>,
) -> Result<T, HttpError> {
    let mut last = HttpError::Failed("no attempt".into());
    for i in 0..tries.max(1) {
        if i > 0 {
            sleep(pause);
        }
        match f() {
            Ok(v) => return Ok(v),
            Err(e @ HttpError::Failed(_)) => last = e,
            Err(e) => return Err(e),
        }
    }
    Err(last)
}

/// Arguments for `sekantor-hub.exe`: the same `up` the service runs, without a browser.
/// `up` takes the port as an option and ignores `SEKANTOR_PORT`, so pass it on.
pub fn hub_args(port: u16, log_file: &Path) -> Vec<OsString> {
    let mut args: Vec<OsString> = vec!["up".into(), "--no-open".into()];
    if port != DEFAULT_PORT {
        args.push("--port".into());
        args.push(port.to_string().into());
    }
    args.push("--log-file".into());
    args.push(log_file.as_os_str().to_owned());
    args
}

/// Spawn the hub detached and windowless; it keeps running after the app exits.
pub fn spawn_hub(hub_exe: &Path, port: u16, home: &Path) -> io::Result<()> {
    let mut cmd = crate::setup::hidden_command(hub_exe);
    cmd.args(hub_args(port, &home.join("hub.log")))
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: no console, and no Ctrl+C from our group.
        cmd.creation_flags(crate::setup::CREATE_NO_WINDOW | 0x0000_0200);
    }
    cmd.spawn().map(drop)
}

/// The hub's HTTP API, with the token read fresh on each call (the hub writes it on first start).
pub struct Hub {
    pub port: u16,
    pub home: PathBuf,
    agent: ureq::Agent,
}

impl Hub {
    pub fn new(port: u16, home: PathBuf) -> Self {
        let agent = ureq::AgentBuilder::new().timeout(HTTP_TIMEOUT).build();
        Hub { port, home, agent }
    }

    fn auth(&self) -> Result<String, HttpError> {
        read_token(&self.home)
            .map(|t| format!("Bearer {t}"))
            .ok_or(HttpError::Rejected(401))
    }

    fn get_once(&self, path: &str) -> Result<serde_json::Value, HttpError> {
        let req = self.agent.get(&format!("{}{path}", base_url(self.port)));
        read_json(req.set("Authorization", &self.auth()?).call())
    }

    fn post_once(&self, path: &str) -> Result<serde_json::Value, HttpError> {
        let req = self.agent.post(&format!("{}{path}", base_url(self.port)));
        read_json(
            req.set("Authorization", &self.auth()?)
                .send_json(serde_json::json!({})),
        )
    }

    fn with_retry<T>(&self, f: impl FnMut() -> Result<T, HttpError>) -> Result<T, HttpError> {
        retry(HTTP_TRIES, HTTP_PAUSE, std::thread::sleep, f)
    }

    /// `GET /v1/health` answers `{"ok": true}` with our token.
    pub fn healthy(&self) -> bool {
        self.with_retry(|| self.get_once("/v1/health"))
            .map(|v| v.get("ok") == Some(&serde_json::Value::Bool(true)))
            .unwrap_or(false)
    }

    /// A fresh one-time login URL for the window (`POST /v1/login-code`, bearer only).
    pub fn login_url(&self) -> Result<String, String> {
        let v = self
            .with_retry(|| self.post_once("/v1/login-code"))
            .map_err(|e| e.to_string())?;
        let path = v.get("path").and_then(|p| p.as_str()).unwrap_or_default();
        let code = code_from_path(path).ok_or_else(|| format!("unexpected login-code answer: {v}"))?;
        Ok(login_url(self.port, &code))
    }

    /// The first-run state (`GET /v1/setup`, bearer only): the JSON `sekantor setup --json` prints.
    pub fn setup_status(&self) -> Result<crate::setup::SetupStatus, String> {
        let v = self
            .with_retry(|| self.get_once("/v1/setup"))
            .map_err(|e| e.to_string())?;
        crate::setup::status_from_json(v)
    }

    /// `POST /v1/shutdown`; the hub exits within about a second.
    pub fn shutdown(&self) -> Result<(), String> {
        match self.with_retry(|| self.post_once("/v1/shutdown")) {
            Ok(_) | Err(HttpError::Refused) => Ok(()),
            Err(e) => Err(e.to_string()),
        }
    }
}

fn read_json(res: Result<ureq::Response, ureq::Error>) -> Result<serde_json::Value, HttpError> {
    match res {
        Ok(resp) => resp
            .into_json::<serde_json::Value>()
            .map_err(|e| HttpError::Failed(e.to_string())),
        Err(ureq::Error::Status(code, _)) if code < 500 => Err(HttpError::Rejected(code)),
        Err(ureq::Error::Status(code, _)) => Err(HttpError::Failed(format!("HTTP {code}"))),
        Err(ureq::Error::Transport(t)) if matches!(t.kind(), ureq::ErrorKind::ConnectionFailed) => {
            Err(HttpError::Refused)
        }
        Err(ureq::Error::Transport(t)) => Err(HttpError::Failed(t.to_string())),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::{Cell, RefCell};

    fn temp_home(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("sekantor-desktop-test-{name}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    /// A fake clock that only moves when the code under test sleeps (or a health check "takes" time).
    struct FakeClock {
        now: Cell<Duration>,
        slept: Cell<Duration>,
    }

    impl FakeClock {
        fn new() -> Self {
            FakeClock { now: Cell::new(Duration::ZERO), slept: Cell::new(Duration::ZERO) }
        }
        fn sleep(&self, d: Duration) {
            self.now.set(self.now.get() + d);
            self.slept.set(self.slept.get() + d);
        }
        fn advance(&self, d: Duration) {
            self.now.set(self.now.get() + d);
        }
        fn now(&self) -> Duration {
            self.now.get()
        }
    }

    #[test]
    fn ensure_hub_healthy_does_not_launch() {
        let launches = Cell::new(0);
        let clock = FakeClock::new();
        let r = ensure_hub(
            || {
                launches.set(launches.get() + 1);
                Ok(())
            },
            || true,
            |d| clock.sleep(d),
            || clock.now(),
        );
        assert_eq!(r, Ok(()));
        assert_eq!(launches.get(), 0);
        assert_eq!(clock.slept.get(), Duration::ZERO);
    }

    #[test]
    fn ensure_hub_starts_a_hub_when_none_runs() {
        // Review focus 1: first install or after Quit, nothing answers; the app starts one and goes on.
        let launches = Cell::new(0);
        let checks = Cell::new(0);
        let clock = FakeClock::new();
        let r = ensure_hub(
            || {
                launches.set(launches.get() + 1);
                Ok(())
            },
            || {
                checks.set(checks.get() + 1);
                checks.get() > 3 // the first check plus two polls fail; the third poll answers
            },
            |d| clock.sleep(d),
            || clock.now(),
        );
        assert_eq!(r, Ok(()));
        assert_eq!(launches.get(), 1);
        assert_eq!(checks.get(), 4);
        assert_eq!(clock.slept.get(), POLL_EVERY * 3);
    }

    #[test]
    fn ensure_hub_gives_up_after_the_timeout() {
        let launches = Cell::new(0);
        let clock = FakeClock::new();
        let r = ensure_hub(
            || {
                launches.set(launches.get() + 1);
                Ok(())
            },
            || false,
            |d| clock.sleep(d),
            || clock.now(),
        );
        assert!(r.is_err());
        assert_eq!(launches.get(), 1);
        assert_eq!(clock.slept.get(), POLL_FOR);
    }

    #[test]
    fn ensure_hub_timeout_is_wall_time_when_health_checks_are_slow() {
        // Each health check of a busy hub takes 10 s (3 tries x timeout): the wait still ends near 30 s.
        let checks = Cell::new(0);
        let clock = FakeClock::new();
        let r = ensure_hub(
            || Ok(()),
            || {
                checks.set(checks.get() + 1);
                clock.advance(Duration::from_secs(10));
                false
            },
            |d| clock.sleep(d),
            || clock.now(),
        );
        assert!(r.is_err());
        assert_eq!(checks.get(), 4); // the first check, then 3 polls of 10.5 s each pass 30 s
        assert!(clock.now() < POLL_FOR + Duration::from_secs(15));
    }

    #[test]
    fn wait_for_gives_the_service_hub_a_grace_period() {
        let checks = Cell::new(0);
        let clock = FakeClock::new();
        let up = wait_for(
            || {
                checks.set(checks.get() + 1);
                checks.get() == 4
            },
            |d| clock.sleep(d),
            || clock.now(),
            SERVICE_GRACE,
        );
        assert!(up);
        assert_eq!(clock.slept.get(), POLL_EVERY * 4);
        let clock = FakeClock::new();
        assert!(!wait_for(|| false, |d| clock.sleep(d), || clock.now(), SERVICE_GRACE));
        assert_eq!(clock.slept.get(), SERVICE_GRACE);
    }

    #[test]
    fn monotonic_clock_moves_forward() {
        let clock = monotonic();
        let a = clock();
        assert!(clock() >= a);
    }

    #[test]
    fn ensure_hub_reports_a_failed_launch() {
        let r = ensure_hub(
            || Err(io::Error::new(io::ErrorKind::NotFound, "no exe")),
            || false,
            |_| panic!("must not poll after a failed launch"),
            || Duration::ZERO,
        );
        assert!(r.unwrap_err().contains("no exe"));
    }

    #[test]
    fn retry_succeeds_after_two_failures() {
        // Review focus 2: a busy hub times out twice, then answers; the window must not fail.
        let calls = Cell::new(0);
        let pauses = RefCell::new(Vec::new());
        let r = retry(3, HTTP_PAUSE, |d| pauses.borrow_mut().push(d), || {
            calls.set(calls.get() + 1);
            if calls.get() < 3 {
                Err(HttpError::Failed("timed out".into()))
            } else {
                Ok("code")
            }
        });
        assert_eq!(r, Ok("code"));
        assert_eq!(calls.get(), 3);
        assert_eq!(*pauses.borrow(), vec![HTTP_PAUSE, HTTP_PAUSE]);
    }

    #[test]
    fn retry_gives_up_after_the_last_try() {
        let calls = Cell::new(0);
        let r: Result<(), _> = retry(3, HTTP_PAUSE, |_| {}, || {
            calls.set(calls.get() + 1);
            Err(HttpError::Failed("timed out".into()))
        });
        assert_eq!(r, Err(HttpError::Failed("timed out".into())));
        assert_eq!(calls.get(), 3);
    }

    #[test]
    fn retry_stops_when_nothing_listens_or_the_hub_refuses() {
        for err in [HttpError::Refused, HttpError::Rejected(403)] {
            let calls = Cell::new(0);
            let r: Result<(), _> = retry(3, HTTP_PAUSE, |_| {}, || {
                calls.set(calls.get() + 1);
                Err(err.clone())
            });
            assert_eq!(r, Err(err));
            assert_eq!(calls.get(), 1);
        }
    }

    #[test]
    fn read_token_trims_the_newline() {
        let home = temp_home("token");
        std::fs::write(home.join("token"), "abc123\r\n").unwrap();
        assert_eq!(read_token(&home), Some("abc123".to_string()));
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn read_token_missing_or_empty_is_none() {
        let home = temp_home("notoken");
        assert_eq!(read_token(&home), None);
        std::fs::write(home.join("token"), "\n").unwrap();
        assert_eq!(read_token(&home), None);
        let _ = std::fs::remove_dir_all(&home);
    }

    #[test]
    fn login_url_points_at_loopback() {
        assert_eq!(login_url(7878, "xyz"), "http://127.0.0.1:7878/?login=xyz");
        assert_eq!(login_url(9000, "a-b_c"), "http://127.0.0.1:9000/?login=a-b_c");
    }

    #[test]
    fn code_from_path_reads_the_hub_answer() {
        assert_eq!(code_from_path("/?login=abc_DEF-1"), Some("abc_DEF-1".to_string()));
        assert_eq!(code_from_path("/?login="), None);
        assert_eq!(code_from_path("/other"), None);
        assert_eq!(code_from_path("/?login=a&x=//evil"), None);
    }

    #[test]
    fn home_dir_prefers_sekantor_home() {
        let env = |k: &str| match k {
            "SEKANTOR_HOME" => Some(r"D:\custom".to_string()),
            "USERPROFILE" => Some(r"C:\Users\First Last".to_string()),
            _ => None,
        };
        assert_eq!(home_dir_from(env), PathBuf::from(r"D:\custom"));
        let env = |k: &str| match k {
            "USERPROFILE" => Some(r"C:\Users\First Last".to_string()),
            _ => None,
        };
        assert_eq!(home_dir_from(env), PathBuf::from(r"C:\Users\First Last").join(".sekantor"));
    }

    #[test]
    fn port_defaults_to_7878() {
        assert_eq!(port_from(None), 7878);
        assert_eq!(port_from(Some("9001".into())), 9001);
        assert_eq!(port_from(Some("nope".into())), 7878);
    }

    #[test]
    fn hub_args_run_up_without_a_browser() {
        let log = PathBuf::from(r"C:\Users\First Last\.sekantor\hub.log");
        let args = hub_args(7878, &log);
        let want: Vec<OsString> = vec!["up".into(), "--no-open".into(), "--log-file".into(), log.clone().into()];
        assert_eq!(args, want);
        let args = hub_args(9001, &log);
        assert_eq!(&args[2..4], &[OsString::from("--port"), OsString::from("9001")]);
    }

    #[test]
    fn calls_to_a_closed_port_are_refused_not_retried() {
        // Bind then drop a listener to find a free loopback port, so this touches no real hub.
        let port = std::net::TcpListener::bind("127.0.0.1:0").unwrap().local_addr().unwrap().port();
        let home = temp_home("closed");
        std::fs::write(home.join("token"), "t").unwrap();
        let hub = Hub::new(port, home.clone());
        assert_eq!(hub.get_once("/v1/health"), Err(HttpError::Refused));
        assert!(!hub.healthy());
        assert_eq!(hub.get_once("/v1/setup"), Err(HttpError::Refused));
        assert!(hub.setup_status().unwrap_err().contains("not running"));
        assert_eq!(hub.shutdown(), Ok(()));
        let _ = std::fs::remove_dir_all(&home);
    }
}
