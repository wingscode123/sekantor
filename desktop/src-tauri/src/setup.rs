//! First run: ask the bundled `sekantor.exe setup` whether hooks and the service are in place, and
//! install them when the user presses "Connect Claude Code".
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
pub const STATUS_TIMEOUT: Duration = Duration::from_secs(20);
pub const APPLY_TIMEOUT: Duration = Duration::from_secs(60);

/// What `sekantor.exe setup --json` (and `--apply`) prints.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct SetupStatus {
    /// "missing" | "outdated" | "ok"
    pub hooks: String,
    pub hook_path: Option<String>,
    pub service: bool,
    /// "absent" | "off" | "on"
    pub openbot: String,
    pub orca: bool,
    pub tmux: bool,
}

impl SetupStatus {
    /// The first-run page is needed until hooks point at this install and the service is set up.
    pub fn needs_first_run(&self) -> bool {
        self.hooks != "ok" || !self.service
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
