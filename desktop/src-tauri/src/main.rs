// No console window next to the app in release builds.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod hub;
mod setup;

use serde::Serialize;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::TrayIconBuilder;
use tauri::{AppHandle, Manager, WindowEvent};

use setup::{Bundle, SetupStatus};

/// What `ui/setup.js` shows: the first-run page, or "opening your office".
#[derive(Serialize)]
struct Start {
    first_run: bool,
    status: Option<SetupStatus>,
    error: Option<String>,
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

/// Make sure a hub runs, then load the office in the main window with a one-time login link.
fn open_office_now(app: &AppHandle) -> Result<(), String> {
    let bundle = bundle(app)?;
    let (port, home) = (hub::hub_port(), hub::home_dir());
    let client = hub::Hub::new(port, home.clone());
    hub::ensure_hub(
        || hub::spawn_hub(&bundle.hub(), port, &home),
        || client.healthy(),
        std::thread::sleep,
    )?;
    let url = tauri::Url::parse(&client.login_url()?).map_err(|e| e.to_string())?;
    let win = app.get_webview_window("main").ok_or("the main window is gone")?;
    win.navigate(url).map_err(|e| e.to_string())?;
    show_main(app);
    Ok(())
}

/// "Quit SeKantor": stop the hub, then the app. Closing the window only hides it.
fn quit(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.hide();
    }
    let app = app.clone();
    std::thread::spawn(move || {
        let _ = hub::Hub::new(hub::hub_port(), hub::home_dir()).shutdown();
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

/// The "Connect Claude Code" button: `sekantor.exe setup --apply`, then open the office.
#[tauri::command]
async fn connect(app: AppHandle) -> Result<(), String> {
    blocking(move || {
        bundle(&app)?.apply()?;
        open_office_now(&app)
    })
    .await
}

#[tauri::command]
async fn open_office(app: AppHandle) -> Result<(), String> {
    blocking(move || open_office_now(&app)).await
}

fn main() {
    tauri::Builder::default()
        // Registered first, as the plugin asks: a second launch shows the running window and exits.
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| show_main(app)))
        .invoke_handler(tauri::generate_handler![status, connect, open_office])
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .setup(|app| {
            let open = MenuItem::with_id(app, "open", "Open SeKantor", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "Quit SeKantor", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&open, &quit_item])?;
            let mut tray = TrayIconBuilder::with_id("main")
                .tooltip("SeKantor")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_main(app),
                    "quit" => quit(app),
                    _ => {}
                });
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }
            tray.build(app)?;
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running SeKantor");
}
