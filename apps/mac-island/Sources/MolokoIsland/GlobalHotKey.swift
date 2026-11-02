import AppKit
import Carbon.HIToolbox

/// A key combination for the global hotkey: a virtual key code plus Carbon modifier flags.
struct HotKeyCombo: Equatable {
    let id: String
    let keyCode: UInt32
    /// Carbon modifiers (`cmdKey`, `shiftKey`, `optionKey`, `controlKey`).
    let modifiers: UInt32
    /// How menus show it, modifiers in Apple's order ⌃⌥⇧⌘.
    let title: String

    static let space = UInt32(kVK_Space)

    /// The choices offered in the island's context menu (⌥Space is the default).
    static let presets: [HotKeyCombo] = [
        HotKeyCombo(id: "option-space", keyCode: space, modifiers: UInt32(optionKey), title: "⌥Пробел"),
        HotKeyCombo(id: "control-option-space", keyCode: space, modifiers: UInt32(controlKey | optionKey), title: "⌃⌥Пробел"),
        HotKeyCombo(id: "shift-command-space", keyCode: space, modifiers: UInt32(shiftKey | cmdKey), title: "⇧⌘Пробел"),
        HotKeyCombo(id: "control-shift-space", keyCode: space, modifiers: UInt32(controlKey | shiftKey), title: "⌃⇧Пробел"),
    ]
    static let defaultID = "option-space"
    /// Stored instead of a preset id when the owner switched the hotkey off.
    static let offID = "off"

    static func preset(id: String) -> HotKeyCombo? {
        presets.first { $0.id == id }
    }
}

/// The system-wide hotkey that opens the island (Carbon `RegisterEventHotKey`).
///
/// Carbon hotkeys need no Accessibility permission: the system delivers only the registered
/// combination to us, never other keystrokes. Registration is exclusive, so it fails when another
/// app already holds the same combination exclusively; enabled system shortcuts (Keyboard →
/// Keyboard Shortcuts, e.g. input-source switching) are checked separately, because the system
/// would swallow them before us without any error.
@MainActor
final class GlobalHotKey {
    enum State: Equatable {
        case off
        case active(HotKeyCombo)
        /// Another app registered the same combination.
        case takenByApp(HotKeyCombo)
        /// An enabled macOS keyboard shortcut uses it.
        case takenBySystem(HotKeyCombo)
        case failed(HotKeyCombo, OSStatus)

        var combo: HotKeyCombo? {
            switch self {
            case .off: nil
            case .active(let c), .takenByApp(let c), .takenBySystem(let c), .failed(let c, _): c
            }
        }

        var isActive: Bool {
            if case .active = self { return true }
            return false
        }

        /// Russian explanation for the owner when the combination could not be used.
        var problem: String? {
            switch self {
            case .off, .active: nil
            case .takenByApp(let c): "\(c.title) уже занято другим приложением."
            case .takenBySystem(let c):
                "\(c.title) уже занято сочетанием macOS (Системные настройки → Клавиатура → Сочетания клавиш)."
            case .failed(let c, let status): "Не удалось назначить \(c.title) (код \(status))."
            }
        }
    }

    var onPress: (() -> Void)?
    private(set) var state: State = .off

    private var hotKeyRef: EventHotKeyRef?
    private var handlerRef: EventHandlerRef?
    private var lastPress = Date.distantPast

    init() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let status = InstallEventHandler(
            GetApplicationEventTarget(), hotKeyEventHandler, 1, &spec,
            Unmanaged.passUnretained(self).toOpaque(), &handlerRef
        )
        if status != noErr { Log.error("hotkey handler not installed (\(status))") }
    }

    /// Registers `combo` (nil switches the hotkey off) and returns the resulting state.
    @discardableResult
    func register(_ combo: HotKeyCombo?) -> State {
        unregister()
        guard let combo else {
            state = .off
            Log.info("hotkey off")
            return state
        }
        if Self.systemShortcutUses(combo) {
            state = .takenBySystem(combo)
        } else {
            var ref: EventHotKeyRef?
            let id = EventHotKeyID(signature: hotKeySignature, id: 1)
            let status = RegisterEventHotKey(
                combo.keyCode, combo.modifiers, id, GetApplicationEventTarget(),
                OptionBits(kEventHotKeyExclusive), &ref
            )
            if status == noErr, let ref {
                hotKeyRef = ref
                state = .active(combo)
            } else if status == OSStatus(eventHotKeyExistsErr) {
                state = .takenByApp(combo)
            } else {
                state = .failed(combo, status)
            }
        }
        Log.info("hotkey \(combo.id): \(state.isActive ? "registered" : (state.problem ?? "failed"))")
        return state
    }

    private func unregister() {
        if let hotKeyRef { UnregisterEventHotKey(hotKeyRef) }
        hotKeyRef = nil
    }

    fileprivate func pressed() {
        // Auto-repeat while the keys are held would toggle the island back and forth.
        let now = Date()
        guard now.timeIntervalSince(lastPress) > 0.35 else { return }
        lastPress = now
        onPress?()
    }

    /// Whether an enabled system-wide keyboard shortcut (Keyboard → Keyboard Shortcuts) uses
    /// exactly this combination.
    static func systemShortcutUses(_ combo: HotKeyCombo) -> Bool {
        var unmanaged: Unmanaged<CFArray>?
        guard CopySymbolicHotKeys(&unmanaged) == noErr,
              let entries = unmanaged?.takeRetainedValue() as? [[String: Any]] else { return false }
        let mask = UInt32(cmdKey | shiftKey | optionKey | controlKey)
        return entries.contains { entry in
            guard (entry["kHISymbolicHotKeyEnabled"] as? Bool) == true,
                  let code = (entry["kHISymbolicHotKeyCode"] as? NSNumber)?.uint32Value,
                  let modifiers = (entry["kHISymbolicHotKeyModifiers"] as? NSNumber)?.uint32Value
            else { return false }
            return code == combo.keyCode && (modifiers & mask) == (combo.modifiers & mask)
        }
    }

    /// Enabled system shortcuts on the Space key, raw (debug command `shortcuts`).
    static func debugSystemShortcuts() -> [String] {
        var unmanaged: Unmanaged<CFArray>?
        guard CopySymbolicHotKeys(&unmanaged) == noErr,
              let entries = unmanaged?.takeRetainedValue() as? [[String: Any]] else { return [] }
        return entries.compactMap { entry in
            guard let code = (entry["kHISymbolicHotKeyCode"] as? NSNumber)?.uint32Value, code == HotKeyCombo.space else { return nil }
            let modifiers = (entry["kHISymbolicHotKeyModifiers"] as? NSNumber)?.uint32Value ?? 0
            let enabled = (entry["kHISymbolicHotKeyEnabled"] as? Bool) ?? false
            return "mods=0x\(String(modifiers, radix: 16)) enabled=\(enabled)"
        }
    }
}

/// 'MLKI' — tells our hotkey events apart from anyone else's.
private let hotKeySignature: OSType = 0x4D4C_4B49

/// Carbon delivers hotkey events on the main thread (the main run loop's event dispatcher).
private func hotKeyEventHandler(_: EventHandlerCallRef?, event: EventRef?, userData: UnsafeMutableRawPointer?) -> OSStatus {
    guard let event, let userData else { return OSStatus(eventNotHandledErr) }
    var id = EventHotKeyID()
    let status = GetEventParameter(
        event, EventParamName(kEventParamDirectObject), EventParamType(typeEventHotKeyID),
        nil, MemoryLayout<EventHotKeyID>.size, nil, &id
    )
    guard status == noErr, id.signature == hotKeySignature else { return OSStatus(eventNotHandledErr) }
    let hotKey = Unmanaged<GlobalHotKey>.fromOpaque(userData).takeUnretainedValue()
    MainActor.assumeIsolated { hotKey.pressed() }
    return noErr
}
