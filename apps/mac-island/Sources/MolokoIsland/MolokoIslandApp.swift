import AppKit

@main
@MainActor
enum MolokoIslandMain {
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.accessory) // no Dock icon (LSUIElement in the bundle too)
        app.run()
        withExtendedLifetime(delegate) {}
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private let web = WebIsland()
    private let setup = SetupWindowController()
    private var controller: IslandController?
    private var notifier: ApprovalNotifier?
    private let hotKey = GlobalHotKey()
    private var debug: DebugCommands?

    func applicationWillFinishLaunching(_ notification: Notification) {
        // The notification delegate must be in place before launching ends: a click on a
        // notification may be what launched the app.
        notifier = ApprovalNotifier()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        installMainMenu()
        let controller = IslandController(web: web)
        self.controller = controller
        controller.onChangeAddress = { [weak self] in self?.showSetup(firstRun: false) }
        controller.hasOtherWindowOpen = { [weak self] in self?.setup.isVisible ?? false }
        wireApprovals(controller)
        controller.hotKey = hotKey
        hotKey.onPress = { [weak controller] in controller?.toggleFromHotKey() }
        let hotKeyState = hotKey.register(AppSettings.shared.hotKeyCombo)
        if hotKeyState.problem != nil {
            // After launch settles, not in the middle of it.
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak controller] in
                controller?.reportHotKeyProblem(hotKeyState)
            }
        }

        setup.onSave = { [weak self] url in self?.useServer(url) }
        setup.onQuit = { NSApp.terminate(nil) }
        setup.onClose = { [weak self] in
            guard let self, self.controller?.mode != .expanded else { return }
            NSApp.deactivate()
        }

        // MOLOKO_ISLAND_SERVER=<address> overrides the saved address for this run only (development).
        let override = ProcessInfo.processInfo.environment["MOLOKO_ISLAND_SERVER"].flatMap(ServerAddress.normalize)
        let server = override ?? AppSettings.shared.serverURL
        web.load(server: server)
        if server == nil { showSetup(firstRun: true) }
        if Log.debugEnabled {
            debug = DebugCommands(controller: controller, setup: setup, notifier: notifier, hotKey: hotKey)
        }
        Log.info("started, version \(AppInfo.version), server \(override != nil ? "from MOLOKO_ISLAND_SERVER" : (server == nil ? "not set" : "set"))")
    }

    /// Approval notifications: the page reports approvals, the notifier shows them and sends the
    /// owner's answer back through the page.
    private func wireApprovals(_ controller: IslandController) {
        guard let notifier else { return }
        controller.notifier = notifier
        web.onApproval = { [weak notifier] id, summary, agent in notifier?.approvalAppeared(id: id, summary: summary, agent: agent) }
        web.onApprovalGone = { [weak notifier] id in notifier?.approvalGone(id: id) }
        web.onApprovalsPending = { [weak notifier] ids in notifier?.syncPending(ids: ids) }
        web.onApprovalResolved = { [weak notifier] id, ok, message in notifier?.actionFinished(id: id, ok: ok, message: message) }
        notifier.sendToPage = { [weak web] id, action in web?.sendApprovalAction(action, approvalId: id) }
        notifier.isPageReady = { [weak controller] in controller?.isPageReady ?? false }
        notifier.onOpenIsland = { [weak controller] in controller?.openHeld(focus: nil) }
        controller.onPageReady = { [weak notifier] in notifier?.pageReady() }
    }

    private func showSetup(firstRun: Bool) {
        setup.show(current: AppSettings.shared.serverURL, firstRun: firstRun)
    }

    private func useServer(_ url: URL) {
        AppSettings.shared.serverURL = url
        Log.info("server address saved")
        controller?.serverChanged()
        web.load(server: url)
        controller?.expand(makeKey: true) // show the page right away (it may ask to log in)
    }

    /// LSUIElement apps have no visible menu bar, but copy/paste shortcuts in the web view and
    /// the address field still go through the main menu's key equivalents. Deliberately no
    /// ⌘Q/⌘H: they would quit/hide the island when it merely holds the keyboard focus.
    private func installMainMenu() {
        let main = NSMenu()
        let appItem = NSMenuItem()
        appItem.submenu = NSMenu()
        main.addItem(appItem)

        let editItem = NSMenuItem()
        let edit = NSMenu(title: "Правка")
        edit.addItem(withTitle: "Отменить", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Повторить", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Вырезать", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Скопировать", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Вставить", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Выбрать всё", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        editItem.submenu = edit
        main.addItem(editItem)
        NSApp.mainMenu = main
    }
}
