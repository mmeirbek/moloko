import AppKit

/// Remote control for manual testing, active only when launched with `MOLOKO_ISLAND_DEBUG=1`.
/// Send a command as a distributed notification named `kz.moloko.island.debug` whose
/// `object` is the command: expand, expand-key, focus-web, escape, collapse, peek, pin,
/// unpin, reload, state, probe, snapshot:<absolute path>.
@MainActor
final class DebugCommands: NSObject {
    private let controller: IslandController
    private let setup: SetupWindowController

    init(controller: IslandController, setup: SetupWindowController) {
        self.controller = controller
        self.setup = setup
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
        default:
            if command.hasPrefix("snapshot:") {
                controller.debugSnapshot(to: String(command.dropFirst("snapshot:".count)))
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
        let script = "JSON.stringify({ island: window.molokoIsland || null, log: window.__islandLog || null, path: location.pathname, visibility: document.visibilityState })"
        controller.web.webView.evaluateJavaScript(script) { result, error in
            if let text = result as? String {
                Log.info("probe: \(text)")
            } else {
                Log.error("probe failed: \(error?.localizedDescription ?? "no result")")
            }
        }
    }
}
