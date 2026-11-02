import AppKit

/// Remote control for manual testing, active only when launched with `MOLOKO_ISLAND_DEBUG=1`.
/// Send a command as a distributed notification named `kz.moloko.island.debug` whose
/// `object` is the command: expand, expand-key, focus-web, escape, collapse, peek, pin,
/// unpin, reload, state, probe, snapshot:<absolute path>; hotkey (as if the global hotkey was
/// pressed), hotkey-preset:<id|off> (as if chosen in the menu), menu (log the context menu),
/// shortcuts (log the system shortcuts on the Space key); notifications (log the
/// permission and delivered ones), notify-provisional (quiet permission without the prompt, for
/// test builds), clear-notifications, respond:<approve|reject|open>:<approval id> (as if a
/// notification button or the notification itself was clicked).
@MainActor
final class DebugCommands: NSObject {
    private let controller: IslandController
    private let setup: SetupWindowController
    private let notifier: ApprovalNotifier?
    private let hotKey: GlobalHotKey

    init(controller: IslandController, setup: SetupWindowController, notifier: ApprovalNotifier?, hotKey: GlobalHotKey) {
        self.controller = controller
        self.setup = setup
        self.notifier = notifier
        self.hotKey = hotKey
        super.init()
        DistributedNotificationCenter.default().addObserver(
            self, selector: #selector(handle(_:)),
            name: Notification.Name("kz.moloko.island.debug"), object: nil,
            suspensionBehavior: .deliverImmediately
        )
        Log.info("debug commands enabled")
    }

    @objc private func handle(_ notification: Notification) {
        guard let command = notification.object as? String else { return }
        Log.info("debug command: \(command)")
        switch command {
        case "expand": controller.expand(makeKey: false)
        case "expand-key": controller.expand(makeKey: true)
        case "focus-web":
            controller.panel.makeKey()
            controller.panel.makeFirstResponder(controller.web.webView)
        case "escape": postEscape()
        case "collapse": controller.collapse()
        case "peek": controller.peek()
        case "pin": controller.setPinned(true)
        case "unpin": controller.setPinned(false)
        case "reload": controller.web.reload()
        case "state": Log.info("state: \(controller.debugState) setupVisible=\(setup.isVisible)")
        case "probe": probePage()
        case "hotkey": controller.toggleFromHotKey()
        case "menu": Log.info("menu: \(controller.debugMenu)")
        case "shortcuts": Log.info("system shortcuts on Space: \(GlobalHotKey.debugSystemShortcuts()) hotkey=\(hotKey.state)")
        case "notifications": notifier?.debugReport()
        case "notify-provisional": notifier?.debugRequestProvisional()
        case "clear-notifications": notifier?.debugClear()
        default:
            if command.hasPrefix("snapshot:") {
                controller.debugSnapshot(to: String(command.dropFirst("snapshot:".count)))
            } else if command.hasPrefix("hotkey-preset:") {
                controller.chooseHotKey(id: String(command.dropFirst("hotkey-preset:".count)))
            } else if command.hasPrefix("respond:") {
                let parts = command.split(separator: ":", maxSplits: 2).map(String.init)
                guard parts.count == 3 else { return }
                notifier?.handleResponse(action: parts[1], approvalId: parts[2])
            } else {
                Log.error("unknown debug command")
            }
        }
    }

    /// Escape through the normal event path (key window → first responder → page → panel).
    private func postEscape() {
        guard let event = NSEvent.keyEvent(
            with: .keyDown, location: .zero, modifierFlags: [],
            timestamp: ProcessInfo.processInfo.systemUptime,
            windowNumber: controller.panel.windowNumber, context: nil,
            characters: "\u{1b}", charactersIgnoringModifiers: "\u{1b}",
            isARepeat: false, keyCode: 53
        ) else { return }
        NSApp.postEvent(event, atStart: false)
    }

    /// Reads what the page saw (the test page keeps a log in `window.__islandLog`).
    private func probePage() {
        let script = "JSON.stringify({ island: window.molokoIsland || null, log: window.__islandLog || null, path: location.pathname, visibility: document.visibilityState, active: document.activeElement && (document.activeElement.id || document.activeElement.tagName), focused: document.hasFocus() })"
        controller.web.webView.evaluateJavaScript(script) { result, error in
            if let text = result as? String {
                Log.info("probe: \(text)")
            } else {
                Log.error("probe failed: \(error?.localizedDescription ?? "no result")")
            }
        }
    }
}
