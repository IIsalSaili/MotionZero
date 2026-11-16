// Pont Iris : un petit serveur HTTP local (127.0.0.1 seulement) qui lance des commandes de VS Code.
// Pas de touche simulée : la commande marche quel que soit l'endroit du focus (panneau Claude, terminal…).
// Chaque réponse dit si l'effet a bien eu lieu (onglet actif changé), pour qu'Iris n'annonce jamais à tort.
// Plusieurs fenêtres VS Code : la première prend le port ; les autres réessaient toutes les 5 s.
const vscode = require("vscode");
const http = require("http");

const PORT = 47613;
const COMMANDS = {
  next: "workbench.action.nextEditor",
  prev: "workbench.action.previousEditor",
};

let server = null;
let retry = null;

function activeTab() {
  const group = vscode.window.tabGroups.activeTabGroup;
  if (!group) return null;
  const tab = group.activeTab;
  return { group: group.viewColumn, index: tab ? group.tabs.indexOf(tab) : -1, label: tab ? tab.label : "" };
}

function tabCount() {
  return vscode.window.tabGroups.all.reduce((n, g) => n + g.tabs.length, 0);
}

async function run(name) {
  const command = COMMANDS[name];
  if (!command) return { ok: false, reason: "commande inconnue" };
  if (tabCount() < 2) return { ok: false, reason: "un seul onglet" };
  const before = activeTab();
  await vscode.commands.executeCommand(command);
  await new Promise((r) => setTimeout(r, 60));
  const after = activeTab();
  const moved = !before || !after || before.group !== after.group || before.index !== after.index;
  return moved ? { ok: true, label: after ? after.label : "" } : { ok: false, reason: "onglet inchange" };
}

function listen() {
  server = http.createServer((req, res) => {
    const name = (req.url || "").replace(/^\/+/, "");
    const reply = (obj) => {
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify(obj));
    };
    if (name === "ping") return reply({ ok: true });
    run(name).then(reply, (e) => reply({ ok: false, reason: String(e && e.message || e) }));
  });
  server.on("error", () => {          // port pris (autre fenêtre VS Code) : on réessaie plus tard
    server = null;
    retry = setTimeout(listen, 5000);
  });
  server.listen(PORT, "127.0.0.1");
}

function activate(context) {
  listen();
  context.subscriptions.push({ dispose: deactivate });
}

function deactivate() {
  if (retry) clearTimeout(retry);
  if (server) server.close();
}

module.exports = { activate, deactivate };
