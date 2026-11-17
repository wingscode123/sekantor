fn main() {
    // Declaring the app's commands puts them under the ACL: a page may call one only when a
    // capability grants `allow-<command>` to it (capabilities/default.json grants them to the bundled
    // page only, never to the hub page on 127.0.0.1).
    tauri_build::try_build(
        tauri_build::Attributes::new().app_manifest(
            tauri_build::AppManifest::new().commands(&["status", "connect", "open_office"]),
        ),
    )
    .expect("failed to run tauri-build");
}
