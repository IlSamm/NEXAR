// NEXAR per Mac: una finestra con la dashboard del PC, ovunque tu sia.
// Il PC pubblica il suo indirizzo (tunnel Cloudflare, cambia a ogni avvio) cifrato su ntfy.sh: qui lo si legge,
// lo si decifra e si apre NEXAR con il token di questo Mac. Il primo collegamento usa il codice generato sul PC.
// Accensione: Wake-on-LAN diretto in casa, e da fuori una richiesta cifrata che il relay su Umbrel ascolta.
// Aggiornamenti: controlla le release su GitHub e si sostituisce da sola con un clic (zip verificato con SHA-256).
// Stesso formato di beacon.py (vettore di prova in selfTest e in tests/test_beacon.py).
import AppKit
import CryptoKit
import Darwin
import Foundation
import Security
import SwiftUI
import UserNotifications
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
        let plain = Data(zip(ct, stream(secret, nonce, ct.count)).map { $0 ^ $1 })
        return (try? JSONSerialization.jsonObject(with: plain)) as? [String: Any]
    }

    static func stream(_ secret: String, _ nonce: Data, _ size: Int) -> Data {
        let ek = SymmetricKey(data: derive(secret, "enc"))
        var out = Data()
        var i: UInt32 = 0
        while out.count < size {
            let counter = Data([UInt8(i >> 24 & 0xff), UInt8(i >> 16 & 0xff), UInt8(i >> 8 & 0xff), UInt8(i & 0xff)])
            out += Data(HMAC<SHA256>.authenticationCode(for: nonce + counter, using: ek))
            i += 1
        }
        return out
    }

    static func seal(_ secret: String, _ obj: [String: Any]) -> String? {
        guard let data = try? JSONSerialization.data(withJSONObject: obj) else { return nil }
        var nb = [UInt8](repeating: 0, count: 16)
        guard SecRandomCopyBytes(kSecRandomDefault, nb.count, &nb) == errSecSuccess else { return nil }
        let nonce = Data(nb)
        let ct = Data(zip(data, stream(secret, nonce, data.count)).map { $0 ^ $1 })
        let tag = Data(HMAC<SHA256>.authenticationCode(for: nonce + ct, using: SymmetricKey(data: derive(secret, "mac")))).prefix(16)
        return (nonce + ct + Data(tag)).base64EncodedString()
            .replacingOccurrences(of: "+", with: "-").replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
}

// MARK: - Wake-on-LAN (in casa)

enum WOL {
    static func send(mac: String, broadcast: String) -> Bool {
        let hex = Array(mac.filter { $0.isHexDigit })
        guard hex.count == 12 else { return false }
        var macBytes: [UInt8] = []
        for i in stride(from: 0, to: 12, by: 2) {
            guard let b = UInt8(String(hex[i...i + 1]), radix: 16) else { return false }
            macBytes.append(b)
        }
        var packet = [UInt8](repeating: 0xff, count: 6)
        for _ in 0..<16 { packet += macBytes }
        let fd = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
        guard fd >= 0 else { return false }
        defer { close(fd) }
        var on: Int32 = 1
        setsockopt(fd, SOL_SOCKET, SO_BROADCAST, &on, socklen_t(MemoryLayout<Int32>.size))
        var sent = false
        for dst in Set([broadcast, "255.255.255.255"]) where !dst.isEmpty {
            var addr = sockaddr_in()
            addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
            addr.sin_family = sa_family_t(AF_INET)
            addr.sin_port = in_port_t(9).bigEndian
            guard inet_pton(AF_INET, dst, &addr.sin_addr) == 1 else { continue }
            for _ in 0..<3 {
                let r = packet.withUnsafeBytes { buf in
                    withUnsafePointer(to: &addr) { ptr in
                        ptr.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                            sendto(fd, buf.baseAddress, buf.count, 0, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
                        }
                    }
                }
                if r > 0 { sent = true }
            }
        }
        return sent
    }
}

func selfTest() -> Bool {
    let secret = "pair:ABCDEFGH"
    let sealed = "AAECAwQFBgcICQoLDA0OD4i-mlEBkcequE5WalzA51ADDgfRgtYNoxG5oNq3LX397ojxLxhewRevh1Ibg0TDo_dewj47tup9dVv354aayyMtOp5Gj05HF1GwNdPXpJQr_b-uJZRwdZGbfVcs_zN53f7-fepdshXhKg"
    guard Seal.topic(secret) == "nexar-687e95d18aab6f3771d80bc6d695cc25" else { print("topic sbagliato: \(Seal.topic(secret))"); return false }
    guard let p = Seal.unseal(secret, sealed), p["url"] as? String == "https://example.trycloudflare.com",
          p["bot"] as? String == "nexar_bot", (p["t"] as? NSNumber)?.intValue == 1700000000 else { print("decifratura sbagliata"); return false }
    guard Seal.unseal("pair:ABCDEFGX", sealed) == nil else { print("chiave sbagliata accettata"); return false }
    guard let again = Seal.seal("wake:x", ["wake": 5]), (Seal.unseal("wake:x", again)?["wake"] as? NSNumber)?.intValue == 5 else { print("cifratura sbagliata"); return false }
    guard Model.isNewer("1.0.41", than: "1.0.40"), !Model.isNewer("1.0.40", than: "1.0.40"), Model.isNewer("1.0.10", than: "1.0.9"),
          !Model.isNewer("2.0.0", than: "dev") else { print("confronto versioni sbagliato"); return false }
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
    var mac: String?
    var bc: String?
}

enum UpdateError: Error { case download, checksum, archive }

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

struct Found { let url: String; let bot: String; let t: Double; let mac: String; let bc: String }

struct Update { let version: String; let zip: URL; let sha: URL?; let page: URL }

// MARK: - Logica

@MainActor
final class Model: ObservableObject {
    enum Screen: Equatable { case pair, searching, off, web(URL) }

    @Published var screen: Screen = .searching
    @Published var busy = false
    @Published var error = ""
    @Published var reloadToken = 0
    @Published var wakeStatus = ""
    @Published var waking = false
    @Published var update: Update?
    @Published var updating = ""
    var saved: Saved? = Store.load()
    private var retry: Task<Void, Never>?

    var token: String { saved?.token ?? "" }
    var bot: String { saved?.bot ?? "" }

    private var started = false

    func start() {
        if started { return }
        started = true
        if saved == nil { screen = .pair } else { Task { await connect() } }
        Task { await pollLoop() }
        Task {
            while !Task.isCancelled {
                await checkUpdate()
                try? await Task.sleep(nanoseconds: 6 * 3600 * 1_000_000_000)
            }
        }
    }

    // MARK: stato per la barra dei menu e le notifiche

    @Published var live: Live?
    @Published var pcOn: Bool?
    private var misses = 0
    private var hotAt = Date.distantPast

    func pollLoop() async {
        Notify.ask()
        while !Task.isCancelled {
            await poll()
            try? await Task.sleep(nanoseconds: 10_000_000_000)
        }
    }

    func poll() async {
        guard let s = saved, !s.url.isEmpty, let url = URL(string: s.url + "/api/status") else { live = nil; return }
        var req = URLRequest(url: url, timeoutInterval: 8)
        req.setValue(token, forHTTPHeaderField: "X-PC-ECO-Key")
        if let got = try? await URLSession.shared.data(for: req), (got.1 as? HTTPURLResponse)?.statusCode == 200,
           let o = (try? JSONSerialization.jsonObject(with: got.0)) as? [String: Any] {
            func num(_ v: Any?) -> Double? { (v as? NSNumber)?.doubleValue }
            let l = Live(cpu: num(o["cpu"]), gpu: num(o["gpu"]), cpuTemp: num(o["cpu_temp"]), gpuTemp: num(o["gpu_temp"]),
                         watts: num((o["power"] as? [String: Any])?["total"]), mode: o["mode"] as? String ?? "normal")
            if pcOn == false { Notify.send("PC acceso", "NEXAR è di nuovo raggiungibile.") }
            pcOn = true; misses = 0; live = l
            let hot = (l.cpuTemp ?? 0) >= 85 || (l.gpuTemp ?? 0) >= 83
            if hot && Date().timeIntervalSince(hotAt) > 900 {
                hotAt = Date()
                Notify.send("Temperatura alta", "CPU \(fmt(l.cpuTemp, " °C")) · GPU \(fmt(l.gpuTemp, " °C"))")
            }
        } else {
            misses += 1
            if misses >= 2 {
                if pcOn == true { Notify.send("PC non raggiungibile", "Il PC è spento oppure NEXAR è stato chiuso.") }
                pcOn = false; live = nil
                // l'indirizzo cambia quando il PC si riaccende: cerca quello nuovo
                if let f = await Model.latest(s.beacon), f.url != s.url, var cur = saved {
                    cur.url = f.url; saved = cur; Store.save(cur)
                }
            }
        }
    }

    func command(_ path: String, _ body: [String: String]) {
        Task {
            guard let s = saved, let url = URL(string: s.url + path) else { return }
            var req = URLRequest(url: url, timeoutInterval: 10)
            req.httpMethod = "POST"
            req.setValue(token, forHTTPHeaderField: "X-PC-ECO-Key")
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
            _ = try? await URLSession.shared.data(for: req)
            await poll()
        }
    }

    // MARK: accensione

    func wake() async {
        guard let s = saved, !waking else { return }
        waking = true; wakeStatus = "Invio il segnale di accensione…"
        defer { waking = false }
        let local = WOL.send(mac: s.mac ?? "", broadcast: s.bc ?? "")
        let t = Int(Date().timeIntervalSince1970)
        var ack: [String: Any]?
        if let body = Seal.seal("wake:" + s.beacon, ["wake": t]), let url = URL(string: "\(ntfyBase)/\(Seal.topic("wake:" + s.beacon))") {
            var req = URLRequest(url: url, timeoutInterval: 12)
            req.httpMethod = "POST"
            req.httpBody = Data(body.utf8)
            req.setValue("no", forHTTPHeaderField: "Firebase")
            req.setValue("NEXAR-Mac/\(appVersion)", forHTTPHeaderField: "User-Agent")
            if (try? await URLSession.shared.data(for: req)) != nil {
                for _ in 0..<8 {
                    try? await Task.sleep(nanoseconds: 2_500_000_000)
                    ack = await Model.ack(s.beacon, t)
                    if ack != nil { break }
                }
            }
        }
        if let a = ack {
            wakeStatus = (a["on"] as? Bool) == true ? "Umbrel vede il PC già acceso: aspetto che NEXAR risponda…"
                                                     : "Segnale inviato da Umbrel ✓ Il PC si sta accendendo: NEXAR si apre qui da sola."
        } else if local {
            wakeStatus = "Segnale inviato nella rete di casa. Da fuori casa serve l'app NEXAR su Umbrel: installala dal tuo store e premi Collega Umbrel in NEXAR sul PC."
        } else {
            wakeStatus = "Non sono riuscito a inviare il segnale: controlla la connessione e che l'app NEXAR su Umbrel sia accesa."
        }
        retry?.cancel()
        retry = Task { [weak self] in
            for _ in 0..<12 {
                try? await Task.sleep(nanoseconds: 10_000_000_000)
                if Task.isCancelled { return }
                guard let self, self.screen == .off else { return }
                await self.connect()
            }
        }
    }

    static func ack(_ secret: String, _ t: Int) async -> [String: Any]? {
        guard let url = URL(string: "\(ntfyBase)/\(Seal.topic("ack:" + secret))/json?poll=1&since=5m") else { return nil }
        var req = URLRequest(url: url, timeoutInterval: 10)
        req.setValue("NEXAR-Mac/\(appVersion)", forHTTPHeaderField: "User-Agent")
        guard let got = try? await URLSession.shared.data(for: req), let text = String(data: got.0, encoding: .utf8) else { return nil }
        for line in text.split(separator: "\n") {
            guard let o = (try? JSONSerialization.jsonObject(with: Data(line.utf8))) as? [String: Any], let msg = o["message"] as? String,
                  let p = Seal.unseal("ack:" + secret, msg), (p["ack"] as? NSNumber)?.intValue == t else { continue }
            return p
        }
        return nil
    }

    // MARK: aggiornamenti

    nonisolated static func isNewer(_ a: String, than b: String) -> Bool {
        let pa = a.split(separator: ".").compactMap { Int($0) }, pb = b.split(separator: ".").compactMap { Int($0) }
        guard pa.count == 3, pb.count == 3 else { return false }
        return pb.lexicographicallyPrecedes(pa)
    }

    func checkUpdate(manual: Bool = false) async {
        guard let url = URL(string: "https://api.github.com/repos/IlSamm/NEXAR/releases/latest") else { return }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.setValue("NEXAR-Mac/\(appVersion)", forHTTPHeaderField: "User-Agent")
        req.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        guard let got = try? await URLSession.shared.data(for: req), (got.1 as? HTTPURLResponse)?.statusCode == 200,
              let o = (try? JSONSerialization.jsonObject(with: got.0)) as? [String: Any], let tag = o["tag_name"] as? String,
              let assets = o["assets"] as? [[String: Any]] else {
            if manual { updating = "Non riesco a controllare gli aggiornamenti adesso." }
            return
        }
        let v = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
        func asset(_ n: String) -> URL? {
            (assets.first { $0["name"] as? String == n }?["browser_download_url"] as? String).flatMap { URL(string: $0) }
        }
        guard Model.isNewer(v, than: appVersion), let zip = asset("NEXAR-Mac.zip") else {
            update = nil
            if manual { updating = "Hai già l'ultima versione (\(appVersion))." }
            return
        }
        update = Update(version: v, zip: zip, sha: asset("NEXAR-Mac.zip.sha256"),
                        page: URL(string: o["html_url"] as? String ?? "") ?? URL(string: "https://github.com/IlSamm/NEXAR/releases/latest")!)
        if manual { updating = "" }
    }

    func installUpdate() async {
        guard let u = update else { return }
        let bundle = URL(fileURLWithPath: Bundle.main.bundlePath)
        let parent = bundle.deletingLastPathComponent()
        guard bundle.pathExtension == "app", FileManager.default.isWritableFile(atPath: parent.path) else {
            NSWorkspace.shared.open(u.page)
            updating = "Sposta NEXAR in Applicazioni per aggiornarla da sola. Intanto ti ho aperto la pagina di download."
            return
        }
        updating = "Scarico NEXAR \(u.version)…"
        do {
            let (file, resp) = try await URLSession.shared.download(from: u.zip)
            guard (resp as? HTTPURLResponse)?.statusCode == 200 else { throw UpdateError.download }
            let data = try Data(contentsOf: file)
            if let shaURL = u.sha {
                let (shaData, _) = try await URLSession.shared.data(from: shaURL)
                let expected = String(decoding: shaData, as: UTF8.self)
                    .split(whereSeparator: { $0 == " " || $0 == "\n" }).first.map { $0.lowercased() } ?? ""
                let actual = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
                guard expected == actual else { throw UpdateError.checksum }
            }
            updating = "Installo NEXAR \(u.version)…"
            let work = FileManager.default.temporaryDirectory.appendingPathComponent("nexar-update-\(UUID().uuidString)", isDirectory: true)
            try FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)
            let zipPath = work.appendingPathComponent("NEXAR-Mac.zip")
            try data.write(to: zipPath)
            let unzip = Process()
            unzip.executableURL = URL(fileURLWithPath: "/usr/bin/ditto")
            unzip.arguments = ["-x", "-k", zipPath.path, work.path]
            try unzip.run()
            unzip.waitUntilExit()
            let fresh = work.appendingPathComponent("NEXAR.app")
            guard unzip.terminationStatus == 0,
                  FileManager.default.isExecutableFile(atPath: fresh.appendingPathComponent("Contents/MacOS/NEXAR").path) else { throw UpdateError.archive }
            func q(_ s: String) -> String { "'" + s.replacingOccurrences(of: "'", with: "'\\''") + "'" }
            let old = bundle.path
            let pid = ProcessInfo.processInfo.processIdentifier
            // Aspetta che questa app si chiuda, sostituisce il pacchetto (senza mai restare senza app) e la riapre.
            let script = [
                "while kill -0 \(pid) 2>/dev/null; do sleep 0.3; done",
                "rm -rf \(q(old + ".new")) \(q(old + ".old"))",
                "if mv \(q(fresh.path)) \(q(old + ".new")); then",
                "  if mv \(q(old)) \(q(old + ".old")); then",
                "    if mv \(q(old + ".new")) \(q(old)); then rm -rf \(q(old + ".old")); else mv \(q(old + ".old")) \(q(old)); fi",
                "  fi",
                "fi",
                "xattr -dr com.apple.quarantine \(q(old)) 2>/dev/null",
                "open \(q(old))",
                "rm -rf \(q(work.path))",
            ].joined(separator: "\n") + "\n"
            let scriptPath = work.appendingPathComponent("update.sh")
            try script.write(to: scriptPath, atomically: true, encoding: .utf8)
            let runner = Process()
            runner.executableURL = URL(fileURLWithPath: "/bin/sh")
            runner.arguments = ["-c", "nohup /bin/sh \(q(scriptPath.path)) >/dev/null 2>&1 &"]
            try runner.run()
            runner.waitUntilExit()
            NSApp.terminate(nil)
        } catch {
            updating = "Aggiornamento non riuscito (\(error)). Riprova, oppure scaricala dalla pagina delle release."
        }
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
            if best == nil || t >= best!.t {
                best = Found(url: u, bot: p["bot"] as? String ?? "", t: t, mac: p["mac"] as? String ?? "", bc: p["bc"] as? String ?? "")
            }
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
        if screen == .pair { screen = .searching }
        var candidates: [String] = []
        if let f = await Model.latest(s.beacon) {
            candidates.append(f.url)
            if !f.bot.isEmpty { s.bot = f.bot }
            if !f.mac.isEmpty { s.mac = f.mac; s.bc = f.bc }
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

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate, WKScriptMessageHandler, WKDownloadDelegate {
        let model: Model
        weak var web: WKWebView?
        var loaded: URL?
        var reloads = 0
        var downloads: [ObjectIdentifier: URL] = [:]

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
            if action.shouldPerformDownload { return decisionHandler(.download) }
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

        // File scaricati dal PC (cartella condivisa): finiscono in Download sul Mac.
        func webView(_ webView: WKWebView, navigationAction: WKNavigationAction, didBecome download: WKDownload) { download.delegate = self }
        func webView(_ webView: WKWebView, navigationResponse: WKNavigationResponse, didBecome download: WKDownload) { download.delegate = self }

        func download(_ download: WKDownload, decideDestinationUsing response: URLResponse, suggestedFilename: String, completionHandler: @escaping (URL?) -> Void) {
            let dir = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask)[0]
            let clean = suggestedFilename.replacingOccurrences(of: "/", with: "_")
            var target = dir.appendingPathComponent(clean)
            let base = target.deletingPathExtension().lastPathComponent, ext = target.pathExtension
            var i = 2
            while FileManager.default.fileExists(atPath: target.path) {
                target = dir.appendingPathComponent(ext.isEmpty ? "\(base) (\(i))" : "\(base) (\(i)).\(ext)"); i += 1
            }
            downloads[ObjectIdentifier(download)] = target
            completionHandler(target)
        }

        func downloadDidFinish(_ download: WKDownload) {
            if let url = downloads.removeValue(forKey: ObjectIdentifier(download)) {
                Notify.send("File scaricato", url.lastPathComponent)
                NSWorkspace.shared.activateFileViewerSelecting([url])
            }
        }

        func download(_ download: WKDownload, didFailWithError error: Error, resumeData: Data?) {
            downloads.removeValue(forKey: ObjectIdentifier(download))
        }

        // "Manda file al PC": scelta dei file dal Mac.
        func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo, completionHandler: @escaping ([URL]?) -> Void) {
            let panel = NSOpenPanel()
            panel.allowsMultipleSelection = parameters.allowsMultipleSelection
            panel.canChooseDirectories = false
            panel.canChooseFiles = true
            completionHandler(panel.runModal() == .OK ? panel.urls : nil)
        }

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
            Button(action: { Task { await model.wake() } }) {
                if model.waking { ProgressView().controlSize(.small) } else { Text("⏻  Accendi il PC") }
            }
            .buttonStyle(PrimaryButton(color: Color(red: 0.13, green: 0.77, blue: 0.37)))
            .disabled(model.waking)
            if !model.wakeStatus.isEmpty {
                Text(model.wakeStatus).font(.callout).foregroundColor(.white.opacity(0.85))
                    .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 18) {
                Button("Riprova adesso") { Task { await model.connect() } }.buttonStyle(.link)
                if !model.bot.isEmpty { Button("Apri il bot Telegram") { model.openTelegram() }.buttonStyle(.link) }
            }
        }
    }
}

struct UpdateBanner: View {
    @EnvironmentObject var model: Model
    @State private var hidden = ""

    var body: some View {
        if let u = model.update, hidden != u.version {
            HStack(spacing: 12) {
                Image(systemName: "arrow.down.circle.fill").font(.title2).foregroundColor(accent)
                VStack(alignment: .leading, spacing: 2) {
                    Text("NEXAR \(u.version) per Mac").font(.headline).foregroundColor(.white)
                    Text(model.updating.isEmpty ? "Nuova versione pronta" : model.updating).font(.caption).foregroundColor(.gray)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: 260, alignment: .leading)
                Button("Aggiorna") { Task { await model.installUpdate() } }
                    .buttonStyle(PrimaryButton())
                    .frame(width: 100)
                    .disabled(model.updating.hasPrefix("Scarico") || model.updating.hasPrefix("Installo"))
                Button(action: { hidden = u.version }) { Image(systemName: "xmark").foregroundColor(.gray) }
                    .buttonStyle(.plain)
            }
            .padding(14)
            .background(RoundedRectangle(cornerRadius: 16).fill(Color(red: 0.08, green: 0.09, blue: 0.12)))
            .overlay(RoundedRectangle(cornerRadius: 16).stroke(Color.white.opacity(0.1)))
            .shadow(radius: 18)
        } else if model.update == nil && !model.updating.isEmpty {
            Text(model.updating).font(.caption).foregroundColor(.white).padding(10)
                .background(Capsule().fill(Color(red: 0.08, green: 0.09, blue: 0.12)))
                .onAppear { DispatchQueue.main.asyncAfter(deadline: .now() + 5) { model.updating = "" } }
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
        .overlay(alignment: .bottomTrailing) { UpdateBanner().padding(16) }
        .frame(minWidth: 440, minHeight: 620)
        .preferredColorScheme(.dark)
        .onAppear { model.start() }
    }
}

// MARK: - Barra dei menu e notifiche

struct Live: Equatable {
    var cpu: Double?
    var gpu: Double?
    var cpuTemp: Double?
    var gpuTemp: Double?
    var watts: Double?
    var mode: String
}

enum Notify {
    static func ask() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound]) { _, _ in }
    }

    static func send(_ title: String, _ body: String) {
        let c = UNMutableNotificationContent()
        c.title = title; c.body = body; c.sound = .default
        UNUserNotificationCenter.current().add(UNNotificationRequest(identifier: UUID().uuidString, content: c, trigger: nil))
    }
}

func fmt(_ v: Double?, _ unit: String) -> String {
    guard let v else { return "—" }
    return "\(Int(v.rounded()))\(unit)"
}

struct MenuContent: View {
    @EnvironmentObject var model: Model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        if model.saved == nil {
            Text("Mac non collegato al PC")
        } else if let l = model.live {
            Text("🟢 PC acceso · \(["eco": "AI ECO", "gaming": "Gaming"][l.mode] ?? "Normale")")
            Text("CPU \(fmt(l.cpu, "%")) · \(fmt(l.cpuTemp, " °C"))    GPU \(fmt(l.gpu, "%")) · \(fmt(l.gpuTemp, " °C"))")
            Text("Consumo \(fmt(l.watts, " W"))")
        } else {
            Text(model.pcOn == false ? "🔴 PC spento o NEXAR chiuso" : "Cerco il PC…")
        }
        Divider()
        Button("Apri NEXAR") { openWindow(id: "main"); NSApp.activate(ignoringOtherApps: true) }
        if model.live != nil {
            Menu("Modalità") {
                Button("AI ECO") { model.command("/api/mode", ["mode": "eco"]) }
                Button("Normale") { model.command("/api/mode", ["mode": "normal"]) }
                Button("Gaming") { model.command("/api/mode", ["mode": "gaming"]) }
            }
            Menu("Musica e volume") {
                Button("Play / pausa") { model.command("/api/media", ["action": "play"]) }
                Button("Brano successivo") { model.command("/api/media", ["action": "next"]) }
                Button("Brano precedente") { model.command("/api/media", ["action": "prev"]) }
                Divider()
                Button("Volume su") { model.command("/api/screen/action", ["action": "up"]) }
                Button("Volume giù") { model.command("/api/screen/action", ["action": "down"]) }
                Button("Muto") { model.command("/api/screen/action", ["action": "mute"]) }
            }
            Button("Spegni il monitor") { model.command("/api/screen/action", ["action": "monitor_off"]) }
            Button("Blocca il PC") { model.command("/api/screen/action", ["action": "lock"]) }
        } else if model.saved != nil {
            Button("⏻ Accendi il PC") { Task { await model.wake() } }
        }
        Divider()
        Button("Esci da NEXAR") { NSApp.terminate(nil) }.keyboardShortcut("q")
    }
}

// MARK: - App

final class AppDelegate: NSObject, NSApplicationDelegate {
    // Chiudendo la finestra NEXAR resta nella barra dei menu (icona in alto a destra).
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

struct NexarApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var delegate
    @StateObject private var model = Model()

    var body: some Scene {
        MenuBarExtra {
            MenuContent().environmentObject(model)
        } label: {
            Image(systemName: model.pcOn == true ? "desktopcomputer" : "desktopcomputer.trianglebadge.exclamationmark")
        }
        Window("NEXAR", id: "main") {
            RootView().environmentObject(model)
        }
        .defaultSize(width: 1180, height: 820)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(after: .appInfo) {
                Button("Controlla aggiornamenti…") { Task { await model.checkUpdate(manual: true) } }
            }
            CommandMenu("PC") {
                Button("Ricarica") { Task { await model.connect() } }.keyboardShortcut("r")
                Button("Accendi il PC") { Task { await model.wake() } }.disabled(model.saved == nil)
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
