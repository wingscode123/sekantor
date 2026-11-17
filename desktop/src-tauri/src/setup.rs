//! First run: ask the hub (`GET /v1/setup`) whether hooks and the service are in place, and install
//! them with the bundled `sekantor.exe setup --apply` when the user presses "Connect Claude Code".
//! `sekantor.exe setup --json` is only the fallback when no hub answers: endpoint protection flags
//! each run of the unsigned CLI, so a normal start does not run it.
//!
//! No Tauri types here, so `cargo test` covers it.

use serde::{Deserialize, Serialize};
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant};

/// Windows `CREATE_NO_WINDOW`: a console child gets no console window.
pub const CREATE_NO_WINDOW: u32 = 0x0800_0000;
pub const STATUS_TIMEOUT: Duration = Duration::from_secs(60);
pub const APPLY_TIMEOUT: Duration = Duration::from_secs(60);

/// What `GET /v1/setup` answers and `sekantor.exe setup --json` (and `--apply`) prints.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SetupStatus {
    /// "missing" | "outdated" | "ok"
    pub hooks: String,
    pub hook_path: Option<String>,
    pub service: bool,
    /// The installed task runs this install's hub. Absent in older output: assume it does.
    #[serde(default = "yes")]
    pub service_current: bool,
    /// "absent" | "off" | "on"
    pub openbot: String,
    pub orca: bool,
    pub tmux: bool,
}

fn yes() -> bool {
    true
}

impl SetupStatus {
    /// The first-run page is needed until hooks point at this install and the service is set up.
    pub fn needs_first_run(&self) -> bool {
        self.hooks != "ok" || !self.service || !self.service_current
    }
}

/// The executables inside the bundled PyInstaller folder (`<resources>/sekantor/`).
pub struct Bundle {
    pub dir: PathBuf,
}

impl Bundle {
    pub fn new(resource_dir: &Path) -> Self {
        Bundle { dir: resource_dir.join("sekantor") }
    }

    fn exe(&self, name: &str) -> PathBuf {
        self.dir.join(format!("{name}{}", std::env::consts::EXE_SUFFIX))
    }

    /// The console CLI.
    pub fn cli(&self) -> PathBuf {
        self.exe("sekantor")
    }

    /// The windowed hub launcher (`sekantor-hub.exe up`).
    pub fn hub(&self) -> PathBuf {
        self.exe("sekantor-hub")
    }

    pub fn status(&self) -> Result<SetupStatus, String> {
        parse_status(&run(&self.cli(), &["setup", "--json"], STATUS_TIMEOUT)?)
    }

    pub fn apply(&self) -> Result<SetupStatus, String> {
        parse_status(&run(&self.cli(), &["setup", "--apply"], APPLY_TIMEOUT)?)
    }
}

/// The first-run state for the page. `ensure_hub` makes sure a hub answers (starting one if needed),
/// then `from_hub` asks it. Only when no hub answers, or it cannot report (an older hub without
/// `/v1/setup`), does `from_cli` run `sekantor.exe setup --json`. The fallback is logged.
pub fn first_run_status(
    ensure_hub: impl FnOnce() -> Result<(), String>,
    from_hub: impl FnOnce() -> Result<SetupStatus, String>,
    from_cli: impl FnOnce() -> Result<SetupStatus, String>,
    log: impl Fn(&str),
) -> Result<SetupStatus, String> {
    let why = match ensure_hub() {
        Ok(()) => match from_hub() {
            Ok(s) => return Ok(s),
            Err(e) => format!("the hub could not report the setup: {e}"),
        },
        Err(e) => e,
    };
    log(&format!("first run: {why}; asking sekantor setup --json instead"));
    from_cli().map_err(|e| format!("{why}; {e}"))
}

/// The setup state from the hub's JSON answer.
pub fn status_from_json(v: serde_json::Value) -> Result<SetupStatus, String> {
    let shown = v.to_string();
    serde_json::from_value(v).map_err(|e| format!("unexpected setup answer from the hub ({e}): {shown}"))
}

/// A command that opens no console window on Windows.
pub fn hidden_command(exe: &Path) -> Command {
    #[allow(unused_mut)]
    let mut cmd = Command::new(exe);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }
    cmd
}

fn read_all(pipe: Option<impl Read + Send + 'static>) -> thread::JoinHandle<Vec<u8>> {
    thread::spawn(move || {
        let mut buf = Vec::new();
        if let Some(mut p) = pipe {
            let _ = p.read_to_end(&mut buf);
        }
        buf
    })
}

/// Run the CLI hidden and return its stdout; on a non-zero exit, its message. A child still running
/// after `timeout` is killed, so the first-run page cannot wait forever.
///
/// Caveat: the pipes are read on threads that are joined after the child exits. A grandchild that
/// inherited stdout/stderr (e.g. a hub started by `setup --apply`) keeps them open and delays the
/// join; the CLI starts it through Task Scheduler, which does not inherit them.
pub fn run(exe: &Path, args: &[&str], timeout: Duration) -> Result<String, String> {
    let mut child = hidden_command(exe)
        .args(args)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("could not run {}: {e}", exe.display()))?;
    // Read both pipes on threads so a chatty child never blocks on a full pipe.
    let out = read_all(child.stdout.take());
    let err = read_all(child.stderr.take());
    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => thread::sleep(Duration::from_millis(100)),
            Ok(None) => {
                let _ = child.kill();
                let _ = child.wait();
                return Err(format!(
                    "{} {} did not finish within {} s",
                    exe.display(),
                    args.join(" "),
                    timeout.as_secs()
                ));
            }
            Err(e) => return Err(format!("could not wait for {}: {e}", exe.display())),
        }
    };
    let stdout = String::from_utf8_lossy(&out.join().unwrap_or_default()).into_owned();
    if status.success() {
        return Ok(stdout);
    }
    let stderr = String::from_utf8_lossy(&err.join().unwrap_or_default()).into_owned();
    Err(failure_message(&stderr, &stdout, status.code()))
}

fn failure_message(stderr: &str, stdout: &str, code: Option<i32>) -> String {
    let msg = [stderr.trim(), stdout.trim()]
        .into_iter()
        .find(|m| !m.is_empty())
        .map(str::to_string);
    msg.unwrap_or_else(|| format!("sekantor setup failed (exit {})", code.unwrap_or(-1)))
}

/// The JSON object from `setup` output. Other lines may come first (the one-time "copied from
/// ~/.ronda" notice of `migrate_home`), so take the last line that parses.
pub fn parse_status(stdout: &str) -> Result<SetupStatus, String> {
    stdout
        .lines()
        .rev()
        .map(str::trim)
        .filter(|l| l.starts_with('{'))
        .find_map(|l| serde_json::from_str(l).ok())
        .or_else(|| serde_json::from_str(stdout.trim()).ok())
        .ok_or_else(|| format!("unexpected output from sekantor setup: {}", stdout.trim()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::{Cell, RefCell};

    const OK: &str = r#"{"hooks": "ok", "hook_path": "C:\\Users\\First Last\\AppData\\Local\\SeKantor\\sekantor\\sekantor-hook.exe", "service": true, "openbot": "absent", "orca": false, "tmux": false}"#;

    #[test]
    fn parses_the_setup_json() {
        let s = parse_status(OK).unwrap();
        assert_eq!(s.hooks, "ok");
        assert!(s.service);
        assert!(!s.needs_first_run());
        assert!(s.hook_path.unwrap().ends_with("sekantor-hook.exe"));
    }

    #[test]
    fn skips_notice_lines_before_the_json() {
        let out = format!("Copied token, database from ~/.ronda to ~/.sekantor\n{OK}\n");
        assert_eq!(parse_status(&out).unwrap().hooks, "ok");
    }

    #[test]
    fn parses_pretty_printed_json() {
        let out = "{\n  \"hooks\": \"missing\",\n  \"hook_path\": null,\n  \"service\": false,\n  \"openbot\": \"off\",\n  \"orca\": true,\n  \"tmux\": false\n}\n";
        let s = parse_status(out).unwrap();
        assert_eq!(s.hook_path, None);
        assert!(s.needs_first_run());
    }

    #[test]
    fn garbage_is_an_error() {
        assert!(parse_status("Traceback (most recent call last):").is_err());
        assert!(parse_status("").is_err());
    }

    #[test]
    fn first_run_until_hooks_ok_and_service_on() {
        let base = parse_status(OK).unwrap();
        for (hooks, service, want) in [
            ("ok", true, false),
            ("ok", false, true),
            ("outdated", true, true),
            ("missing", true, true),
        ] {
            let s = SetupStatus { hooks: hooks.into(), service, ..base.clone() };
            assert_eq!(s.needs_first_run(), want, "{hooks} {service}");
        }
    }

    #[test]
    fn first_run_when_the_service_runs_another_install() {
        let s = SetupStatus { service_current: false, ..parse_status(OK).unwrap() };
        assert!(s.needs_first_run());
    }

    #[test]
    fn service_current_defaults_to_true_and_unknown_fields_are_ignored() {
        let s = parse_status(OK).unwrap(); // OK has no service_current
        assert!(s.service_current && !s.needs_first_run());
        let applied = OK.replace("\"tmux\": false}", "\"tmux\": false, \"service_current\": false, \"hub\": \"restart_needed\"}");
        let s = parse_status(&applied).unwrap();
        assert!(!s.service_current && s.needs_first_run());
    }

    fn ok_status() -> SetupStatus {
        parse_status(OK).unwrap()
    }

    #[test]
    fn a_healthy_hub_answers_and_the_cli_does_not_run() {
        let cli_runs = Cell::new(0);
        let logs = RefCell::new(Vec::<String>::new());
        let r = first_run_status(
            || Ok(()),
            || Ok(ok_status()),
            || {
                cli_runs.set(cli_runs.get() + 1);
                Err("must not run".to_string())
            },
            |m| logs.borrow_mut().push(m.to_string()),
        );
        assert_eq!(r, Ok(ok_status()));
        assert_eq!(cli_runs.get(), 0);
        assert!(logs.borrow().is_empty());
    }

    #[test]
    fn no_hub_falls_back_to_the_cli() {
        let hub_asked = Cell::new(false);
        let cli_runs = Cell::new(0);
        let logs = RefCell::new(Vec::<String>::new());
        let r = first_run_status(
            || Err("the SeKantor hub did not answer within 30 s".to_string()),
            || {
                hub_asked.set(true);
                Ok(ok_status())
            },
            || {
                cli_runs.set(cli_runs.get() + 1);
                Ok(SetupStatus { hooks: "missing".into(), ..ok_status() })
            },
            |m| logs.borrow_mut().push(m.to_string()),
        );
        assert_eq!(r.unwrap().hooks, "missing");
        assert!(!hub_asked.get());
        assert_eq!(cli_runs.get(), 1);
        assert_eq!(logs.borrow().len(), 1);
        assert!(logs.borrow()[0].contains("did not answer"));
    }

    #[test]
    fn a_hub_without_the_setup_endpoint_falls_back_to_the_cli() {
        let cli_runs = Cell::new(0);
        let r = first_run_status(
            || Ok(()),
            || Err("the hub refused the request (HTTP 404)".to_string()),
            || {
                cli_runs.set(cli_runs.get() + 1);
                Ok(ok_status())
            },
            |_| {},
        );
        assert_eq!(r, Ok(ok_status()));
        assert_eq!(cli_runs.get(), 1);
    }

    #[test]
    fn both_failing_reports_both_reasons() {
        let r = first_run_status(
            || Err("could not start the SeKantor hub: no exe".to_string()),
            || Ok(ok_status()),
            || Err("could not run sekantor.exe".to_string()),
            |_| {},
        );
        let e = r.unwrap_err();
        assert!(e.contains("no exe") && e.contains("could not run"), "{e}");
    }

    #[test]
    fn status_from_json_reads_the_hub_answer() {
        let v: serde_json::Value = serde_json::from_str(OK).unwrap();
        assert_eq!(status_from_json(v), Ok(ok_status()));
        let v = serde_json::json!({
            "hooks": "outdated", "hook_path": null, "service": true, "service_current": false,
            "openbot": "on", "orca": true, "tmux": false, "extra": 1
        });
        let s = status_from_json(v).unwrap();
        assert!(!s.service_current && s.needs_first_run());
        let e = status_from_json(serde_json::json!({"ok": true})).unwrap_err();
        assert!(e.contains("unexpected setup answer"), "{e}");
    }

    #[test]
    fn bundle_paths_live_in_the_sekantor_folder() {
        let b = Bundle::new(Path::new(r"C:\Users\First Last\AppData\Local\SeKantor"));
        let suffix = std::env::consts::EXE_SUFFIX;
        assert_eq!(b.cli().file_name().unwrap().to_string_lossy(), format!("sekantor{suffix}"));
        assert_eq!(b.hub().file_name().unwrap().to_string_lossy(), format!("sekantor-hub{suffix}"));
        assert_eq!(b.cli().parent().unwrap().file_name().unwrap(), "sekantor");
    }

    #[test]
    fn failure_message_prefers_stderr() {
        assert_eq!(failure_message("boom\n", "out", Some(1)), "boom");
        assert_eq!(failure_message("", "Hooks: could not write\n", Some(1)), "Hooks: could not write");
        assert_eq!(failure_message(" ", "", Some(1)), "sekantor setup failed (exit 1)");
    }

    // A program that exists everywhere CI runs: `ping` on Windows, `sleep`/`echo` elsewhere.
    #[cfg(windows)]
    fn slow() -> (&'static str, Vec<&'static str>) {
        ("ping", vec!["-n", "30", "127.0.0.1"])
    }
    #[cfg(not(windows))]
    fn slow() -> (&'static str, Vec<&'static str>) {
        ("sleep", vec!["30"])
    }

    #[test]
    fn run_kills_a_child_that_hangs() {
        let (exe, args) = slow();
        let started = Instant::now();
        let r = run(Path::new(exe), &args, Duration::from_secs(1));
        assert!(r.unwrap_err().contains("did not finish within 1 s"));
        assert!(started.elapsed() < Duration::from_secs(10));
    }

    #[test]
    fn run_returns_stdout() {
        #[cfg(windows)]
        let r = run(Path::new("cmd"), &["/C", "echo", "hello"], Duration::from_secs(10));
        #[cfg(not(windows))]
        let r = run(Path::new("echo"), &["hello"], Duration::from_secs(10));
        assert_eq!(r.unwrap().trim(), "hello");
    }

    #[test]
    fn a_missing_cli_is_an_error_not_a_panic() {
        let b = Bundle::new(&std::env::temp_dir().join("sekantor-desktop-test-no-bundle"));
        assert!(b.status().unwrap_err().contains("could not run"));
    }
}
