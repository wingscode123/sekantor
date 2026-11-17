// First-run page. Rust decides; this page only shows the answer and calls the app's commands.
const invoke = window.__TAURI__.core.invoke;
const $ = (id) => document.getElementById(id);

function show(section) {
  for (const id of ["starting", "first-run", "problem"]) $(id).hidden = id !== section;
}

function problem(message, again) {
  $("problem-text").textContent = String(message);
  $("retry").onclick = again;
  show("problem");
}

const HOOKS = { ok: "Connected", outdated: "Needs an update", missing: "Not connected" };
const OPENBOT = { on: "Watched", off: "Found, not watched", absent: "Not found" };

function item(label, state, ok) {
  const li = document.createElement("li");
  li.className = ok ? "ok" : "todo";
  li.append(label);
  const s = document.createElement("span");
  s.className = "state";
  s.textContent = state;
  li.append(s);
  return li;
}

function info(label, state) {
  const li = item(label, state, true);
  li.className = "";
  return li;
}

function renderChecks(status) {
  const list = $("checks");
  list.replaceChildren();
  if (!status) return;
  list.append(
    item("Claude Code hooks", HOOKS[status.hooks] || status.hooks, status.hooks === "ok"),
    item("Start the hub at sign-in", status.service && status.service_current ? "On" : "Off", status.service && status.service_current),
    info("OpenBot", OPENBOT[status.openbot] || status.openbot),
    info("Orca", status.orca ? "Found" : "Not found"),
    info("tmux", status.tmux ? "Found" : "Not found"),
  );
}

async function openOffice() {
  show("starting");
  try {
    await invoke("open_office"); // navigates this window to the hub
  } catch (e) {
    problem(e, openOffice);
  }
}

async function connect() {
  const button = $("connect");
  button.disabled = true;
  button.textContent = "Connecting…";
  try {
    await invoke("connect"); // setup --apply, then navigates this window to the hub
  } catch (e) {
    problem(e, start);
  } finally {
    button.disabled = false;
    button.textContent = "Connect Claude Code";
  }
}

async function start() {
  show("starting");
  let s;
  try {
    s = await invoke("status");
  } catch (e) {
    return problem(e, start);
  }
  if (!s.first_run) return openOffice();
  renderChecks(s.status);
  if (s.error) {
    const li = document.createElement("li");
    li.className = "todo";
    li.textContent = s.error;
    $("checks").append(li);
  }
  show("first-run");
}

$("connect").addEventListener("click", connect);
start();
