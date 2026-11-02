import Foundation

enum AppInfo {
    static let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
    /// Name of the WebKit message handler: `window.webkit.messageHandlers.molokoIsland`.
    static let bridgeName = "molokoIsland"
    /// Name of the DOM event dispatched on `window` when the panel opens/closes.
    static let eventName = "moloko-island"
}

/// Validation of the moloko address typed by the owner.
enum ServerAddress {
    /// Accepts `https://name.ts.net`, `name.ts.net` (https is assumed), `http://192.168.1.10:3000`,
    /// and a pasted page link (`https://name.ts.net/island` → `https://name.ts.net`).
    /// Returns `scheme://host[:port]` or nil when the input is not an http(s) address.
    static func normalize(_ raw: String) -> URL? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.contains("://") { text = "https://" + text }
        guard let parts = URLComponents(string: text),
              let scheme = parts.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let host = parts.host?.lowercased(), isValidHost(host),
              parts.user == nil, parts.password == nil
        else { return nil }
        let hostPart = host.contains(":") ? "[\(host)]" : host // IPv6 literal
        let portPart = parts.port.map { ":\($0)" } ?? ""
        return URL(string: "\(scheme)://\(hostPart)\(portPart)")
    }

    private static func isValidHost(_ host: String) -> Bool {
        let allowed = CharacterSet(charactersIn: "abcdefghijklmnopqrstuvwxyz0123456789.-:[]")
        guard !host.isEmpty, host.unicodeScalars.allSatisfy(allowed.contains) else { return false }
        return !host.hasPrefix(".") && !host.hasSuffix(".") && !host.hasPrefix("-")
    }
}

/// Everything the app remembers (UserDefaults domain `kz.moloko.island`).
@MainActor
final class AppSettings {
    static let shared = AppSettings()

    private let defaults = UserDefaults.standard
    private let serverKey = "serverURL"
    private let hotKeyKey = "hotKey"

    var serverURL: URL? {
        get { defaults.string(forKey: serverKey).flatMap(ServerAddress.normalize) }
        set {
            if let newValue {
                defaults.set(newValue.absoluteString, forKey: serverKey)
            } else {
                defaults.removeObject(forKey: serverKey)
            }
        }
    }

    /// Preset id of the global hotkey (`HotKeyCombo.presets`) or `HotKeyCombo.offID`.
    var hotKeyID: String {
        get { defaults.string(forKey: hotKeyKey) ?? HotKeyCombo.defaultID }
        set { defaults.set(newValue, forKey: hotKeyKey) }
    }

    /// The hotkey to register at launch: nil when switched off; an unknown id → the default.
    var hotKeyCombo: HotKeyCombo? {
        let id = hotKeyID
        if id == HotKeyCombo.offID { return nil }
        return HotKeyCombo.preset(id: id) ?? HotKeyCombo.preset(id: HotKeyCombo.defaultID)
    }
}
