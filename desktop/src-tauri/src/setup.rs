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

    /// The Claude Code hook this install registers (what `setup` reports as `hook_path`).
    pub fn hook(&self) -> PathBuf {
        self.exe("sekantor-hook")
    }

    pub fn status(&self) -> Result<SetupStatus, String> {
        parse_status(&run(&self.cli(), &["setup", "--json"], STATUS_TIMEOUT)?)
    }

    pub fn apply(&self) -> Result<SetupStatus, String> {
        parse_status(&run(&self.cli(), &["setup", "--apply"], APPLY_TIMEOUT)?)
    }
}

/// The first-run state for the page. This never starts a hub: starting one before Connect makes
/// `setup --apply` find the port busy, so the login task would not start (`restart_needed`).
/// When `hub_up` says a hub answers, `from_hub` asks it, and its answer counts only when it reports
/// this install's hook (`this_hook`). A hub from another install, such as a source checkout on the
/// same port, describes its own install. Otherwise, or when the hub cannot report (an older hub
/// without `/v1/setup`), `from_cli` runs `sekantor.exe setup --json` once. The fallback is logged.
pub fn first_run_status(
    hub_up: impl FnOnce() -> bool,
    from_hub: impl FnOnce() -> Result<SetupStatus, String>,
    this_hook: &Path,
    from_cli: impl FnOnce() -> Result<SetupStatus, String>,
    log: impl Fn(&str),
) -> Result<SetupStatus, String> {
    let why = if !hub_up() {
        "no hub answers".to_string()
    } else {
        match from_hub() {
            Ok(s) if s.hook_path.as_deref().is_some_and(|p| same_path(p, this_hook)) => return Ok(s),
            Ok(s) => format!(
                "the running hub belongs to another install (hook {})",
                s.hook_path.as_deref().unwrap_or("not found")
            ),
            Err(e) => format!("the hub could not report the setup: {e}"),
        }
    };
    log(&format!("first run: {why}; asking sekantor setup --json instead"));
    from_cli()
}

/// The same file path, ignoring a `\\?\` prefix, slash direction and a trailing slash, and on
/// Windows also letter case.
pub fn same_path(a: &str, b: &Path) -> bool {
    fn norm(p: &str) -> String {
        let p = p.strip_prefix(r"\\?\").unwrap_or(p).replace('\\', "/");
        let p = p.trim_end_matches('/');
        if cfg!(windows) {
            p.to_lowercase()
        } else {
            p.to_string()
        }
    }
    norm(a) == norm(&b.to_string_lossy())
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

    fn this_install() -> Bundle {
        Bundle::new(Path::new(r"C:\Users\First Last\AppData\Local\SeKantor"))
    }

    /// What the hub of this install reports.
    fn hub_status() -> SetupStatus {
        SetupStatus { hook_path: Some(this_install().hook().display().to_string()), ..ok_status() }
    }

    /// What the CLI reports, told apart from the hub's answer by `hooks`.
    fn cli_status() -> SetupStatus {
        SetupStatus { hooks: "missing".into(), ..ok_status() }
    }

    struct Outcome {
        result: Result<SetupStatus, String>,
        hub_asked: bool,
        cli_runs: u32,
        logs: Vec<String>,
    }

    fn first_run(hub_up: bool, hub_answer: Result<SetupStatus, String>) -> Outcome {
        let hub_asked = Cell::new(false);
        let cli_runs = Cell::new(0);
        let logs = RefCell::new(Vec::new());
        let result = first_run_status(
            || hub_up,
            || {
                hub_asked.set(true);
                hub_answer
            },
            &this_install().hook(),
            || {
                cli_runs.set(cli_runs.get() + 1);
                Ok(cli_status())
            },
            |m: &str| logs.borrow_mut().push(m.to_string()),
        );
        Outcome { result, hub_asked: hub_asked.get(), cli_runs: cli_runs.get(), logs: logs.into_inner() }
    }

    #[test]
    fn a_running_hub_of_this_install_answers_and_the_cli_does_not_run() {
        let o = first_run(true, Ok(hub_status()));
        assert_eq!(o.result, Ok(hub_status()));
        assert!(o.hub_asked);
        assert_eq!(o.cli_runs, 0);
        assert!(o.logs.is_empty());
    }

    #[test]
    fn no_hub_runs_the_cli_once_and_does_not_ask_the_hub() {
        let o = first_run(false, Ok(hub_status()));
        assert_eq!(o.result, Ok(cli_status()));
        assert!(!o.hub_asked);
        assert_eq!(o.cli_runs, 1);
        assert_eq!(o.logs.len(), 1);
    }

    #[test]
    fn a_hub_without_the_setup_endpoint_falls_back_to_the_cli() {
        let o = first_run(true, Err("the hub refused the request (HTTP 404)".into()));
        assert_eq!(o.result, Ok(cli_status()));
        assert_eq!(o.cli_runs, 1);
        assert_eq!(o.logs.len(), 1);
    }

    #[test]
    fn a_hub_of_another_install_falls_back_to_the_cli() {
        // The owner's source hub on 7878 reports the venv's hook, not this bundle's.
        let venv = SetupStatus { hook_path: Some(r"D:\Ronda\.venv\Scripts\sekantor-hook.exe".into()), ..ok_status() };
        let o = first_run(true, Ok(venv));
        assert_eq!(o.result, Ok(cli_status()));
        assert_eq!(o.cli_runs, 1);
        let no_hook = SetupStatus { hook_path: None, ..ok_status() };
        assert_eq!(first_run(true, Ok(no_hook)).result, Ok(cli_status()));
    }

    #[test]
    fn a_failing_cli_is_the_error() {
        let r = first_run_status(|| false, || Ok(hub_status()), &this_install().hook(), || Err("boom".into()), |_: &str| {});
        assert_eq!(r, Err("boom".to_string()));
    }

    #[test]
    fn same_path_ignores_slashes_and_the_long_path_prefix() {
        let hook = this_install().hook();
        let shown = hook.display().to_string();
        assert!(same_path(&shown, &hook));
        assert!(same_path(&shown.replace('\\', "/"), &hook));
        assert!(same_path(&format!(r"\\?\{shown}"), &hook));
        assert!(!same_path(r"D:\Ronda\.venv\Scripts\sekantor-hook.exe", &hook));
        // Windows paths ignore case; others do not.
        assert_eq!(same_path(&shown.to_uppercase(), &hook), cfg!(windows));
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
