// NEXAR per Mac: una finestra con la dashboard del PC, ovunque tu sia.
// Il PC pubblica il suo indirizzo (tunnel Cloudflare, cambia a ogni avvio) cifrato su ntfy.sh: qui lo si legge,
// lo si decifra e si apre NEXAR con il token di questo Mac. Il primo collegamento usa il codice generato sul PC.
// Stesso formato di beacon.py (vettore di prova in selfTest e in tests/test_beacon.py).
import AppKit
import CryptoKit
import Foundation
import SwiftUI
import WebKit

let ntfyBase = "https://ntfy.sh"
let codeAlphabet = Set("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
let accent = Color(red: 0.22, green: 0.74, blue: 0.97)
let pageColor = Color(red: 0.035, green: 0.043, blue: 0.059)
let appVersion = (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "dev"

// MARK: - Cifratura (uguale a beacon.py)

enum Seal {
    static func derive(_ secret: String, _ label: String) -> Data {
        Data(HMAC<SHA256>.authenticationCode(for: Data(label.utf8), using: SymmetricKey(data: Data(secret.utf8))))
    }

    static func hex(_ d: Data) -> String { d.map { String(format: "%02x", $0) }.joined() }

    static func topic(_ secret: String) -> String { "nexar-" + String(hex(derive(secret, "topic")).prefix(32)) }

    static func unseal(_ secret: String, _ text: String) -> [String: Any]? {
        var s = text.replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while s.count % 4 != 0 { s += "=" }
        guard let raw = Data(base64Encoded: s), raw.count >= 33 else { return nil }
        let bytes = [UInt8](raw)
        let nonce = Data(bytes[0..<16])
        let ct = Data(bytes[16..<(bytes.count - 16)])
        let tag = Data(bytes[(bytes.count - 16)...])
        let mac = Data(HMAC<SHA256>.authenticationCode(for: nonce + ct, using: SymmetricKey(data: derive(secret, "mac")))).prefix(16)
        guard Data(mac) == tag else { return nil }
        let ek = SymmetricKey(data: derive(secret, "enc"))
        var stream = Data()
        var i: UInt32 = 0
        while stream.count < ct.count {
            let counter = Data([UInt8(i >> 24 & 0xff), UInt8(i >> 16 & 0xff), UInt8(i >> 8 & 0xff), UInt8(i & 0xff)])
            stream += Data(HMAC<SHA256>.authenticationCode(for: nonce + counter, using: ek))
            i += 1
        }
        let plain = Data(zip(ct, stream).map { $0 ^ $1 })
        return (try? JSONSerialization.jsonObject(with: plain)) as? [String: Any]
    }
}

func selfTest() -> Bool {
    let secret = "pair:ABCDEFGH"
    let sealed = "AAECAwQFBgcICQoLDA0OD4i-mlEBkcequE5WalzA51ADDgfRgtYNoxG5oNq3LX397ojxLxhewRevh1Ibg0TDo_dewj47tup9dVv354aayyMtOp5Gj05HF1GwNdPXpJQr_b-uJZRwdZGbfVcs_zN53f7-fepdshXhKg"
    guard Seal.topic(secret) == "nexar-687e95d18aab6f3771d80bc6d695cc25" else { print("topic sbagliato: \(Seal.topic(secret))"); return false }
    guard let p = Seal.unseal(secret, sealed), p["url"] as? String == "https://example.trycloudflare.com",
          p["bot"] as? String == "nexar_bot", (p["t"] as? NSNumber)?.intValue == 1700000000 else { print("decifratura sbagliata"); return false }
    guard Seal.unseal("pair:ABCDEFGX", sealed) == nil else { print("chiave sbagliata accettata"); return false }
    print("selftest ok")
    return true
}

// MARK: - Dati salvati (solo su questo Mac, file leggibile solo dall'utente)

struct Saved: Codable {
    var token: String
    var beacon: String
    var url: String
    var name: String
    var bot: String
}

enum Store {
    static var file: URL {
        let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("NEXAR", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("device.json")
    }

    static func load() -> Saved? {
        guard let d = try? Data(contentsOf: file) else { return nil }
        return try? JSONDecoder().decode(Saved.self, from: d)
    }

    static func save(_ s: Saved?) {
        guard let s, let d = try? JSONEncoder().encode(s) else { try? FileManager.default.removeItem(at: file); return }
        try? d.write(to: file, options: .atomic)
        try? FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
    }
}

struct Found { let url: String; let bot: String; let t: Double }

// MARK: - Logica

@MainActor
final class Model: ObservableObject {
    enum Screen: Equatable { case pair, searching, off, web(URL) }

    @Published var screen: Screen = .searching
    @Published var busy = false
    @Published var error = ""
    @Published var reloadToken = 0
    var saved: Saved? = Store.load()
    private var retry: Task<Void, Never>?

    var token: String { saved?.token ?? "" }
    var bot: String { saved?.bot ?? "" }

    func start() {
        if saved == nil { screen = .pair } else { Task { await connect() } }
    }

    static func latest(_ secret: String) async -> Found? {
        guard let url = URL(string: "\(ntfyBase)/\(Seal.topic(secret))/json?poll=1&since=12h") else { return nil }
        var req = URLRequest(url: url, timeoutInterval: 12)
        req.setValue("NEXAR-Mac/\(appVersion)", forHTTPHeaderField: "User-Agent")
        guard let got = try? await URLSession.shared.data(for: req),
              (got.1 as? HTTPURLResponse)?.statusCode == 200, let text = String(data: got.0, encoding: .utf8) else { return nil }
        var best: Found?
        for line in text.split(separator: "\n") {
            guard let o = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any],
                  o["event"] as? String == "message", let msg = o["message"] as? String,
                  let p = Seal.unseal(secret, msg), let u = p["url"] as? String, u.hasPrefix("https://") else { continue }
            let t = (p["t"] as? NSNumber)?.doubleValue ?? 0
            if best == nil || t >= best!.t { best = Found(url: u, bot: p["bot"] as? String ?? "", t: t) }
        }
        return best
    }

    enum Reach { case ok, unpaired, down }

    func reach(_ base: String) async -> Reach {
        guard let url = URL(string: base + "/api/gateway") else { return .down }
        var req = URLRequest(url: url, timeoutInterval: 10)
        req.setValue(token, forHTTPHeaderField: "X-PC-ECO-Key")
        guard let got = try? await URLSession.shared.data(for: req), let code = (got.1 as? HTTPURLResponse)?.statusCode else { return .down }
        if code == 200 { return .ok }
        if code == 401 { return .unpaired }
        return .down
    }

    func connect() async {
        retry?.cancel()
        guard var s = saved else { screen = .pair; return }
        if case .web = screen {} else { screen = .searching }
        var candidates: [String] = []
        if let f = await Model.latest(s.beacon) {
            candidates.append(f.url)
            if !f.bot.isEmpty { s.bot = f.bot }
        }
        if !s.url.isEmpty && !candidates.contains(s.url) { candidates.append(s.url) }
        for u in candidates {
            switch await reach(u) {
            case .ok:
                s.url = u; saved = s; Store.save(s)
                if let url = URL(string: u + "/"), screen != .web(url) { screen = .web(url) } else { reloadToken += 1 }
                return
            case .unpaired:
                unpair(message: "Questo Mac è stato scollegato dal PC: collegalo di nuovo con un codice.")
                return
            case .down: continue
            }
        }
        saved = s; Store.save(s)
        screen = .off
        retry = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 15_000_000_000)
            if !Task.isCancelled, self?.screen == .off { await self?.connect() }
        }
    }

    /// La pagina segnala un problema: se il PC non risponde più si passa alla schermata "spento".
    func check() {
        Task {
            guard let s = saved else { return }
            switch await reach(s.url) {
            case .ok: break
            case .unpaired: unpair(message: "Questo Mac è stato scollegato dal PC: collegalo di nuovo con un codice.")
            case .down: await connect()
            }
        }
    }

    func pair(code: String, name: String) async {
        let clean = String(code.uppercased().filter { codeAlphabet.contains($0) })
        guard clean.count == 8 else { error = "Il codice ha 8 caratteri, come K7QM-4XPA."; return }
        busy = true; error = ""
        defer { busy = false }
        var found: Found?
        for attempt in 0..<4 {
            found = await Model.latest("pair:" + clean)
            if found != nil { break }
            if attempt < 3 { try? await Task.sleep(nanoseconds: 3_000_000_000) }
        }
        guard let f = found, let url = URL(string: f.url + "/api/devices/pair") else {
            error = "Non trovo il PC con questo codice. Controlla che sia giusto, che non sia scaduto e che NEXAR sia aperto sul PC."
            return
        }
        var req = URLRequest(url: url, timeoutInterval: 20)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let deviceName = name.trimmingCharacters(in: .whitespaces).isEmpty ? "Mac" : name
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["code": clean, "name": deviceName])
        guard let got = try? await URLSession.shared.data(for: req), let http = got.1 as? HTTPURLResponse else {
            error = "Il PC non risponde. Riprova fra qualche secondo."
            return
        }
        let obj = (try? JSONSerialization.jsonObject(with: got.0)) as? [String: Any] ?? [:]
        guard http.statusCode == 200, let token = obj["token"] as? String, let secret = obj["beacon"] as? String else {
            error = (obj["detail"] as? String) ?? "Collegamento non riuscito (\(http.statusCode))."
            return
        }
        saved = Saved(token: token, beacon: secret, url: f.url, name: obj["name"] as? String ?? deviceName, bot: f.bot)
        Store.save(saved)
        await connect()
    }

    func unpair(message: String = "") {
        retry?.cancel()
        saved = nil
        Store.save(nil)
        error = message
        screen = .pair
    }

    func openTelegram() {
        if !bot.isEmpty, let u = URL(string: "https://t.me/\(bot)") { NSWorkspace.shared.open(u) }
    }
}

// MARK: - Dashboard (pagina del PC)

struct WebView: NSViewRepresentable {
    let url: URL
    let token: String
    let reloadToken: Int
    let model: Model

    func makeCoordinator() -> Coordinator { Coordinator(model) }

    func makeNSView(context: Context) -> WKWebView {
        let cfg = WKWebViewConfiguration()
        cfg.applicationNameForUserAgent = "Version/18.0 Safari/605.1.15 NEXARMac/\(appVersion)"
        let tokenJSON = String(data: (try? JSONSerialization.data(withJSONObject: [token])) ?? Data("[\"\"]".utf8), encoding: .utf8) ?? "[\"\"]"
        // L'indirizzo cambia a ogni avvio del PC (e con lui lo spazio di archiviazione): il token si rimette a ogni pagina.
        let js = "try{localStorage.setItem('nexar.device',\(tokenJSON)[0]);}catch(e){}"
        cfg.userContentController.addUserScript(WKUserScript(source: js, injectionTime: .atDocumentStart, forMainFrameOnly: true))
        cfg.userContentController.add(context.coordinator, name: "nexar")
        let web = WKWebView(frame: .zero, configuration: cfg)
        web.navigationDelegate = context.coordinator
        web.uiDelegate = context.coordinator
        web.allowsBackForwardNavigationGestures = false
        web.underPageBackgroundColor = NSColor(red: 0.035, green: 0.043, blue: 0.059, alpha: 1)
        if #available(macOS 13.3, *) { web.isInspectable = true }
        context.coordinator.web = web
        context.coordinator.loaded = url
        context.coordinator.reloads = reloadToken
        web.load(URLRequest(url: url))
        return web
    }

    func updateNSView(_ web: WKWebView, context: Context) {
        let c = context.coordinator
        if c.loaded != url { c.loaded = url; c.reloads = reloadToken; web.load(URLRequest(url: url)) }
        else if c.reloads != reloadToken { c.reloads = reloadToken; web.reload() }
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler {
        let model: Model
        weak var web: WKWebView?
        var loaded: URL?
        var reloads = 0

        init(_ model: Model) { self.model = model }

        func userContentController(_ uc: WKUserContentController, didReceive message: WKScriptMessage) {
            let body = message.body as? String ?? ""
            Task { @MainActor in
                switch body {
                case "unpaired": self.model.unpair(message: "Questo Mac non è più collegato al PC: collegalo di nuovo con un codice.")
                case "logout": self.model.unpair()
                default: self.model.check()
                }
            }
        }

        func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = action.request.url else { return decisionHandler(.cancel) }
            let sameHost = url.host == loaded?.host
            if action.targetFrame?.isMainFrame != false && !sameHost && ["http", "https", "tg", "mailto"].contains(url.scheme ?? "") {
                NSWorkspace.shared.open(url)
                return decisionHandler(.cancel)
            }
            decisionHandler(.allow)
        }

        func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse, decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
            if response.isForMainFrame, let http = response.response as? HTTPURLResponse, http.statusCode >= 500 {
                decisionHandler(.cancel)
                Task { @MainActor in self.model.check() }
                return
            }
            decisionHandler(.allow)
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            if (error as NSError).code == NSURLErrorCancelled { return }
            Task { @MainActor in self.model.check() }
        }

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) { webView.reload() }

        // Link che aprono una nuova finestra: nel browser.
        func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = action.request.url { NSWorkspace.shared.open(url) }
            return nil
        }

        func webView(_ webView: WKWebView, runJavaScriptAlertPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping () -> Void) {
            let a = NSAlert(); a.messageText = "NEXAR"; a.informativeText = message; a.addButton(withTitle: "OK")
            a.runModal(); completionHandler()
        }

        func webView(_ webView: WKWebView, runJavaScriptConfirmPanelWithMessage message: String, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (Bool) -> Void) {
            let a = NSAlert(); a.messageText = "NEXAR"; a.informativeText = message
            a.addButton(withTitle: "OK"); a.addButton(withTitle: "Annulla")
            completionHandler(a.runModal() == .alertFirstButtonReturn)
        }

        func webView(_ webView: WKWebView, runJavaScriptTextInputPanelWithPrompt prompt: String, defaultText: String?, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping (String?) -> Void) {
            let a = NSAlert(); a.messageText = "NEXAR"; a.informativeText = prompt
            let field = NSTextField(frame: NSRect(x: 0, y: 0, width: 260, height: 24)); field.stringValue = defaultText ?? ""
            a.accessoryView = field; a.addButton(withTitle: "OK"); a.addButton(withTitle: "Annulla")
            completionHandler(a.runModal() == .alertFirstButtonReturn ? field.stringValue : nil)
        }
    }
}

// MARK: - Schermate

struct Logo: View {
    var body: some View {
        HStack(spacing: 0) {
            Text("NEX").foregroundColor(.white)
            Text("AR").foregroundColor(accent)
        }
        .font(.system(size: 34, weight: .heavy, design: .rounded))
        .tracking(3)
    }
}

struct Panel<Content: View>: View {
    @ViewBuilder var content: Content
    var body: some View {
        VStack(spacing: 18) { content }
            .padding(32)
            .frame(maxWidth: 420)
            .background(RoundedRectangle(cornerRadius: 22).fill(Color.white.opacity(0.04)))
            .overlay(RoundedRectangle(cornerRadius: 22).stroke(Color.white.opacity(0.08)))
    }
}

struct PrimaryButton: ButtonStyle {
    var color: Color = accent
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 15, weight: .semibold))
            .foregroundColor(.black)
            .padding(.vertical, 12).frame(maxWidth: .infinity)
            .background(RoundedRectangle(cornerRadius: 12).fill(color.opacity(configuration.isPressed ? 0.7 : 1)))
    }
}

struct PairView: View {
    @EnvironmentObject var model: Model
    @State private var code = ""
    @State private var name = Host.current().localizedName ?? "Mac"

    var body: some View {
        Panel {
            Logo()
            Text("Collega questo Mac").font(.title2.weight(.semibold)).foregroundColor(.white)
            Text("Sul PC apri NEXAR → Collegamenti → App per Mac → Genera codice, poi scrivilo qui. Vale 10 minuti.")
                .multilineTextAlignment(.center).foregroundColor(.gray).fixedSize(horizontal: false, vertical: true)
            TextField("K7QM-4XPA", text: $code)
                .textFieldStyle(.plain)
                .font(.system(size: 26, weight: .bold, design: .monospaced))
                .multilineTextAlignment(.center)
                .padding(12)
                .background(RoundedRectangle(cornerRadius: 12).fill(Color.white.opacity(0.06)))
                .onSubmit(go)
            TextField("Nome di questo Mac", text: $name)
                .textFieldStyle(.plain)
                .padding(10)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.white.opacity(0.04)))
            if !model.error.isEmpty {
                Text(model.error).foregroundColor(Color(red: 0.97, green: 0.45, blue: 0.45))
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            }
            Button(action: go) {
                if model.busy { ProgressView().controlSize(.small) } else { Text("Collega") }
            }
            .buttonStyle(PrimaryButton())
            .disabled(model.busy)
            .keyboardShortcut(.defaultAction)
        }
    }

    func go() { Task { await model.pair(code: code, name: name) } }
}

struct SearchingView: View {
    var body: some View {
        VStack(spacing: 18) {
            Logo()
            ProgressView().controlSize(.large)
            Text("Cerco il PC…").foregroundColor(.gray)
        }
    }
}

struct OffView: View {
    @EnvironmentObject var model: Model
    var body: some View {
        Panel {
            Logo()
            Image(systemName: "power").font(.system(size: 40, weight: .semibold)).foregroundColor(Color(red: 0.94, green: 0.27, blue: 0.27))
            Text("Il PC è spento o NEXAR non è aperto").font(.title3.weight(.semibold)).foregroundColor(.white).multilineTextAlignment(.center)
            Text("Riprovo da solo ogni 15 secondi. Appena il PC si accende NEXAR si apre qui.")
                .multilineTextAlignment(.center).foregroundColor(.gray).fixedSize(horizontal: false, vertical: true)
            if !model.bot.isEmpty {
                Button("⏻  Accendi il PC da Telegram") { model.openTelegram() }
                    .buttonStyle(PrimaryButton(color: Color(red: 0.13, green: 0.77, blue: 0.37)))
            }
            Button("Riprova adesso") { Task { await model.connect() } }
                .buttonStyle(.link)
        }
    }
}

struct RootView: View {
    @EnvironmentObject var model: Model
    var body: some View {
        ZStack {
            pageColor.ignoresSafeArea()
            switch model.screen {
            case .pair: PairView()
            case .searching: SearchingView()
            case .off: OffView()
            case .web(let url): WebView(url: url, token: model.token, reloadToken: model.reloadToken, model: model).id(model.token)
            }
        }
        .frame(minWidth: 440, minHeight: 620)
        .preferredColorScheme(.dark)
        .onAppear { model.start() }
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
}

struct NexarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = Model()

    var body: some Scene {
        Window("NEXAR", id: "main") {
            RootView().environmentObject(model)
        }
        .defaultSize(width: 1180, height: 820)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandMenu("PC") {
                Button("Ricarica") { Task { await model.connect() } }.keyboardShortcut("r")
                Button("Accendi da Telegram") { model.openTelegram() }.disabled(model.bot.isEmpty)
                Divider()
                Button("Scollega questo Mac…") {
                    let a = NSAlert()
                    a.messageText = "Scollegare questo Mac?"
                    a.informativeText = "Per usarlo di nuovo servirà un nuovo codice dal PC. Puoi toglierlo del tutto da NEXAR sul PC → Collegamenti."
                    a.addButton(withTitle: "Scollega"); a.addButton(withTitle: "Annulla")
                    if a.runModal() == .alertFirstButtonReturn { model.unpair() }
                }.disabled(model.saved == nil)
            }
        }
    }
}

if CommandLine.arguments.contains("--selftest") { exit(selfTest() ? 0 : 1) }
NexarApp.main()
