// No console window next to the app in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod hub;
mod setup;

use std::io::Write;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use serde::Serialize;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, WindowEvent};

use setup::{Bundle, SetupStatus};

/// The bundled first-run page (Tauri's custom protocol; http://tauri.localhost on Windows).
#[cfg(windows)]
const LOCAL_PAGE: &str = "http://tauri.localhost/index.html";
#[cfg(not(windows))]
const LOCAL_PAGE: &str = "tauri://localhost/index.html";

#[derive(Default)]
struct Shell {
    /// The main window shows the hub's office (not the local page).
    attached: AtomicBool,
    /// The tray icon exists, so a hidden window can be brought back.
    tray: AtomicBool,
}

/// What `ui/setup.js` shows: the first-run page, or "opening your office".
#[derive(Serialize)]
struct Start {
    first_run: bool,
    status: Option<SetupStatus>,
    error: Option<String>,
}

/// One line in `<home>/desktop.log`: a windowed release build has no console to print to.
fn log(message: &str) {
    eprintln!("{message}");
    let home = hub::home_dir();
    if std::fs::create_dir_all(&home).is_ok() {
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(home.join("desktop.log")) {
            let _ = writeln!(f, "{message}");
        }
    }
}

fn bundle(app: &AppHandle) -> Result<Bundle, String> {
    let dir = app.path().resource_dir().map_err(|e| e.to_string())?;
    Ok(Bundle::new(&dir))
}

fn show_main(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.unminimize();
        let _ = w.show();
        let _ = w.set_focus();
    }
}

fn navigate_main(app: &AppHandle, url: &str) -> Result<(), String> {
    let url = tauri::Url::parse(url).map_err(|e| e.to_string())?;
    // `navigate` takes `&mut self` in Tauri 2.0.x and `&self` in later 2.x.
    #[allow(unused_mut)]
    let mut win = app.get_webview_window("main").ok_or("the main window is gone")?;
    win.navigate(url).map_err(|e| e.to_string())
}

/// Make sure a hub runs, then load the office in the main window with a one-time login link.
/// `grace`: wait this long for a hub someone else is starting (the service) before starting one.
fn open_office_now(app: &AppHandle, grace: Duration) -> Result<(), String> {
    let bundle = bundle(app)?;
    let (port, home) = (hub::hub_port(), hub::home_dir());
    let client = hub::Hub::new(port, home.clone());
    if !grace.is_zero() {
        hub::wait_for(|| client.healthy(), std::thread::sleep, hub::monotonic(), grace);
    }
    hub::ensure_hub(
        || hub::spawn_hub(&bundle.hub(), port, &home),
        || client.healthy(),
        std::thread::sleep,
        hub::monotonic(),
    )?;
    navigate_main(app, &client.login_url()?)?;
    app.state::<Shell>().attached.store(true, Ordering::SeqCst);
    show_main(app);
    Ok(())
}

/// "Open SeKantor": show the window; if the hub it shows has gone, start over on the local page,
/// which runs the first-run check and starts a hub again.
fn open_from_tray(app: &AppHandle) {
    show_main(app);
    if !app.state::<Shell>().attached.load(Ordering::SeqCst) {
        return; // the local page is showing and drives itself
    }
    let app = app.clone();
    std::thread::spawn(move || {
        if hub::Hub::new(hub::hub_port(), hub::home_dir()).healthy() {
            return;
        }
        app.state::<Shell>().attached.store(false, Ordering::SeqCst);
        if let Err(e) = navigate_main(&app, LOCAL_PAGE) {
            log(&format!("could not reopen the start page: {e}"));
        }
    });
}

/// "Quit SeKantor": stop the hub, then the app. Closing the window only hides it.
fn quit(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.hide();
    }
    let app = app.clone();
    std::thread::spawn(move || {
        if let Err(e) = hub::Hub::new(hub::hub_port(), hub::home_dir()).shutdown() {
            log(&format!("Quit: the hub did not stop: {e}"));
        }
        app.exit(0);
    });
}

async fn blocking<T: Send + 'static>(
    f: impl FnOnce() -> Result<T, String> + Send + 'static,
) -> Result<T, String> {
    tauri::async_runtime::spawn_blocking(f).await.map_err(|e| e.to_string())?
}

/// Called by the page on load: `sekantor.exe setup --json`.
#[tauri::command]
async fn status(app: AppHandle) -> Result<Start, String> {
    blocking(move || {
        Ok(match bundle(&app)?.status() {
            Ok(s) => Start { first_run: s.needs_first_run(), status: Some(s), error: None },
            Err(e) => Start { first_run: true, status: None, error: Some(e) },
        })
    })
    .await
}

/// The "Connect Claude Code" button: `sekantor.exe setup --apply`, then open the office. Apply
/// starts the service's hub, so wait for it before starting a second one.
#[tauri::command]
async fn connect(app: AppHandle) -> Result<(), String> {
    blocking(move || {
        bundle(&app)?.apply()?;
        open_office_now(&app, hub::SERVICE_GRACE)
    })
    .await
}

#[tauri::command]
async fn open_office(app: AppHandle) -> Result<(), String> {
    blocking(move || open_office_now(&app, Duration::ZERO)).await
}

fn main() {
    tauri::Builder::default()
        // Registered first, as the plugin asks: a second launch shows the running window and exits.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| show_main(app)))
        .manage(Shell::default())
        .invoke_handler(tauri::generate_handler![status, connect, open_office])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // Without a tray icon a hidden window could never come back: let it close.
                if window.state::<Shell>().tray.load(Ordering::SeqCst) {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .setup(|app| {
            let Some(icon) = app.default_window_icon().cloned() else {
                log("SeKantor: no app icon, so no tray icon; closing the window will quit the app");
                return Ok(());
            };
            let open = MenuItem::with_id(app, "open", "Open SeKantor", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit SeKantor", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit_item])?;
            TrayIconBuilder::with_id("main")
                .icon(icon)
                .tooltip("SeKantor")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => open_from_tray(app),
                    "quit" => quit(app),
                    _ => {}
                })
                .build(app)?;
            app.state::<Shell>().tray.store(true, Ordering::SeqCst);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running SeKantor");
}
