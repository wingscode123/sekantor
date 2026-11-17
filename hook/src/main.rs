//! `sekantor-hook`: the Claude Code command hook (ADR-0026). All logic lives in `lib.rs`.

fn main() {
    // panic = "abort" would print the message and end with a non-zero code; a hook does neither.
    std::panic::set_hook(Box::new(|_| std::process::exit(0)));
    std::thread::spawn(|| {
        std::thread::sleep(sekantor_hook::HARD_TIMEOUT);
        std::process::exit(0);
    });
    let env = sekantor_hook::process_env();
    let _ = sekantor_hook::run(std::io::stdin().lock(), &env, cfg!(windows));
    std::process::exit(0);
}
